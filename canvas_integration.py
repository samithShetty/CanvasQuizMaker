"""Canvas LMS Integration for question banks.

This module now exports generated samples into a QTI (IMS QTI 1.2) package
and attempts to import that package into Canvas via the content migration
import endpoint. If the QTI import path fails, we fall back to the previous
per-question creation attempt for compatibility.
"""

import io
import json
import uuid
import zipfile
from typing import Any, Dict, List, Tuple
from xml.sax.saxutils import escape as _escape_xml

import requests
from canvasapi import Canvas
from canvasapi import requester as canvas_requester

from config import CANVAS_TOKEN, CANVAS_URL, COURSE_CODE
from utils import evaluate_expression, render_with_sample

canvas = Canvas(CANVAS_URL, CANVAS_TOKEN)
course = canvas.get_course(COURSE_CODE)
requester = canvas_requester.Requester(CANVAS_URL, CANVAS_TOKEN)


def _escape_html(text: str) -> str:
    """Escape text for safe inclusion in XML."""
    if text is None:
        return ""
    return _escape_xml(str(text))


def _make_mc_item_xml(
    identifier: str,
    title: str,
    question_text: str,
    options: List[str],
    correct_index: int,
    general_comment: str = "",
) -> str:
    """Build a QTI v2.1 multiple-choice assessmentItem with optional general comment."""
    choice_ids = [chr(ord("A") + i) for i in range(len(options))]
    correct_id = (
        choice_ids[correct_index]
        if 0 <= correct_index < len(choice_ids)
        else choice_ids[0]
    )

    escaped_question = _escape_html(question_text)
    escaped_comment = _escape_html(general_comment) if general_comment else ""

    option_xml = []
    for cid, opt in zip(choice_ids, options):
        option_xml.append(
            f'      <simpleChoice identifier="{cid}" fixed="false">{_escape_html(opt)}</simpleChoice>'
        )

    feedback_block = ""
    if escaped_comment:
        feedback_block = f"""
  <modalFeedback identifier="GENERAL" outcomeIdentifier="FEEDBACK" showHide="show">
    <p>{escaped_comment}</p>
  </modalFeedback>"""

    item_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<assessmentItem xmlns="http://www.imsglobal.org/xsd/imsqti_v2p1"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.imsglobal.org/xsd/imsqti_v2p1 http://www.imsglobal.org/xsd/qti/qtiv2p1/imsqti_v2p1.xsd"
    identifier="{_escape_html(identifier)}"
    title="{_escape_html(title)}"
    adaptive="false"
    timeDependent="false">
  <responseDeclaration identifier="RESPONSE" cardinality="single" baseType="identifier">
    <correctResponse>
      <value>{_escape_html(correct_id)}</value>
    </correctResponse>
  </responseDeclaration>
  <outcomeDeclaration identifier="SCORE" cardinality="single" baseType="float">
    <defaultValue>
      <value>1</value>
    </defaultValue>
  </outcomeDeclaration>
  <itemBody>
    <p>{escaped_question}</p>
    <choiceInteraction responseIdentifier="RESPONSE" shuffle="false" maxChoices="1">
      <prompt>{escaped_question}</prompt>
{chr(10).join(option_xml)}
    </choiceInteraction>
  </itemBody>{feedback_block}
  <responseProcessing template="http://www.imsglobal.org/question/qti_v2p1/rptemplates/map_response"/>
</assessmentItem>
'''
    return item_xml


def _make_tf_item_xml(
    identifier: str,
    title: str,
    question_text: str,
    correct_value: str,
    general_comment: str = "",
) -> str:
    """Build a QTI v2.1 true/false item as a 2-option MC."""
    options = ["True", "False"]
    correct_index = 0 if str(correct_value).lower() == "true" else 1
    return _make_mc_item_xml(
        identifier, title, question_text, options, correct_index, general_comment
    )


def _make_open_item_xml(
    identifier: str,
    title: str,
    question_text: str,
    general_comment: str = "",
) -> str:
    """Build a QTI v2.1 open-ended item using extendedTextInteraction and optional general comment."""
    escaped_question = _escape_html(question_text)
    escaped_comment = _escape_html(general_comment) if general_comment else ""

    feedback_block = ""
    if escaped_comment:
        feedback_block = f"""
  <modalFeedback identifier="GENERAL" outcomeIdentifier="FEEDBACK" showHide="show">
    <p>{escaped_comment}</p>
  </modalFeedback>"""

    item_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<assessmentItem xmlns="http://www.imsglobal.org/xsd/imsqti_v2p1"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.imsglobal.org/xsd/imsqti_v2p1 http://www.imsglobal.org/xsd/qti/qtiv2p1/imsqti_v2p1.xsd"
    identifier="{_escape_html(identifier)}"
    title="{_escape_html(title)}"
    adaptive="false"
    timeDependent="false">
  <responseDeclaration identifier="RESPONSE" cardinality="single" baseType="string"/>
  <outcomeDeclaration identifier="SCORE" cardinality="single" baseType="float">
    <defaultValue>
      <value>0</value>
    </defaultValue>
  </outcomeDeclaration>
  <itemBody>
    <p>{escaped_question}</p>
    <extendedTextInteraction responseIdentifier="RESPONSE" expectedLines="3"/>
  </itemBody>{feedback_block}
</assessmentItem>
'''
    return item_xml


def build_qti_v21_package(
    bank_title: str,
    question_template: str,
    template_data: Dict[str, Any],
    samples: List[Dict[str, Any]],
    question_type: str,
) -> Tuple[bytes, str]:
    """Create a QTI v2.1 question bank ZIP from generated samples.

    Returns (zip_bytes, suggested_filename).
    """
    if not samples:
        raise ValueError("No samples available to export.")

    bank_id = f"bank-{uuid.uuid4()}"
    safe_title = bank_title or "question-bank"
    zip_filename = f"{safe_title.replace(' ', '_')}.qti.zip"

    item_filenames: List[str] = []
    manifest_resources: List[str] = []

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, sample in enumerate(samples, start=1):
            q_text = render_with_sample(question_template or "", sample)

            item_identifier = f"item-{idx}"
            item_title = f"{safe_title} #{idx}"

            qti_type = (template_data or {}).get("type")
            include_general = bool((template_data or {}).get("include_general"))
            comment_from_answer = bool((template_data or {}).get("comment_from_answer"))
            general_comment_tpl = (template_data or {}).get("general_comment", "") or ""

            # Default: no general comment text for this sample
            general_comment_text = ""

            if question_type == "Multiple Choice" or qti_type == "mc":
                options: List[str] = []
                for opt in (template_data or {}).get("options", []):
                    rendered_opt = render_with_sample(opt or "", sample)
                    options.append(rendered_opt)

                correct_index = int((template_data or {}).get("correct", 0) or 0)

                if include_general:
                    if comment_from_answer and 0 <= correct_index < len(options):
                        general_comment_text = options[correct_index]
                    elif general_comment_tpl:
                        general_comment_text = render_with_sample(
                            general_comment_tpl, sample
                        )

                item_xml = _make_mc_item_xml(
                    identifier=item_identifier,
                    title=item_title,
                    question_text=q_text,
                    options=options,
                    correct_index=correct_index,
                    general_comment=general_comment_text,
                )
            elif question_type == "True/False" or qti_type == "tf":
                correct_val = (template_data or {}).get("correct", "True")

                if include_general:
                    if comment_from_answer:
                        general_comment_text = str(correct_val)
                    elif general_comment_tpl:
                        general_comment_text = render_with_sample(
                            general_comment_tpl, sample
                        )

                item_xml = _make_tf_item_xml(
                    identifier=item_identifier,
                    title=item_title,
                    question_text=q_text,
                    correct_value=correct_val,
                    general_comment=general_comment_text,
                )
            else:
                # Open-ended style (short answer, essay, fill in the blank, etc.)
                answer_key_expr = (template_data or {}).get("answer_key", "") or ""
                if answer_key_expr:
                    if "{{" in answer_key_expr and "}}" in answer_key_expr:
                        rendered_answer = render_with_sample(answer_key_expr, sample)
                    else:
                        rendered_answer = evaluate_expression(answer_key_expr, sample)
                else:
                    rendered_answer = ""

                if include_general:
                    if comment_from_answer and rendered_answer:
                        general_comment_text = rendered_answer
                    elif general_comment_tpl:
                        general_comment_text = render_with_sample(
                            general_comment_tpl, sample
                        )

                item_xml = _make_open_item_xml(
                    identifier=item_identifier,
                    title=item_title,
                    question_text=q_text,
                    general_comment=general_comment_text,
                )

            item_filename = f"item_{idx}.xml"
            item_filenames.append(item_filename)
            zf.writestr(item_filename, item_xml)

        # Build imsmanifest.xml referencing each item
        resources_xml = []
        for idx, item_filename in enumerate(item_filenames, start=1):
            res_id = f"RES-{idx}"
            resources_xml.append(
                f'''    <resource identifier="{res_id}" type="imsqti_item_xmlv2p1" href="{item_filename}">
      <file href="{item_filename}"/>
    </resource>'''
            )

        manifest_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<manifest xmlns="http://www.imsglobal.org/xsd/imscp_v1p1"
    xmlns:imsqti="http://www.imsglobal.org/xsd/imsqti_v2p1"
    identifier="{_escape_html(bank_id)}">
  <organizations/>
  <resources>
{chr(10).join(resources_xml)}
  </resources>
</manifest>
'''
        zf.writestr("imsmanifest.xml", manifest_xml)

    mem.seek(0)
    return mem.read(), zip_filename
