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
from typing import Any, Dict, List
from xml.sax.saxutils import escape as _escape_xml

import requests
from canvasapi import Canvas
from canvasapi import requester as canvas_requester

from config import CANVAS_TOKEN, CANVAS_URL, COURSE_CODE, TEST_BANK_ID
from utils import evaluate_expression, render_with_sample

canvas = Canvas(CANVAS_URL, CANVAS_TOKEN)
course = canvas.get_course(COURSE_CODE)
requester = canvas_requester.Requester(CANVAS_URL, CANVAS_TOKEN)


def _build_qti_item(
    idx: int,
    sample: Dict[str, Any],
    question_template: str,
    template_data: Dict[str, Any],
) -> str:
    """Build a QTI 1.2 <item> XML string for a single sample.

    This function generates a minimal QTI 1.2 item representation that Canvas
    will accept for import. It is intentionally conservative; richer QTI
    fields can be added later if needed.
    """
    q_text = _escape_xml(render_with_sample(question_template, sample))
    q_type = template_data.get("type", "open")
    item_ident = f"ITEM_{idx+1}"

    if q_type == "mc":
        options = [
            render_with_sample(opt or "", sample)
            for opt in template_data.get("options", [])
        ]
        correct_idx = int(template_data.get("correct", 0))

        choices_xml = []
        for j, opt in enumerate(options):
            choices_xml.append(
                f'<response_label ident="choice{j}"><material><mattext>{_escape_xml(opt)}</mattext></material></response_label>'
            )

        resprocessing = (
            f"<resprocessing><respcondition><conditionvar><varequal>choice{correct_idx}</varequal></conditionvar>"
            '<setvar action="Set">100</setvar></respcondition></resprocessing>'
        )

        item = (
            f'<item ident="{item_ident}"><presentation>'
            f"<material><mattext>{q_text}</mattext></material>"
            '<response_lid ident="response1" rcardinality="Single">'
            "<render_choice>"
            + "".join(choices_xml)
            + "</render_choice></response_lid></presentation>"
            + resprocessing
            + "</item>"
        )

    elif q_type == "tf":
        # True/False as a two-choice MC
        correct = template_data.get("correct", "True")
        correct_idx = 0 if str(correct).lower() in ("true", "t", "1") else 1
        options = ["True", "False"]
        choices_xml = []
        for j, opt in enumerate(options):
            choices_xml.append(
                f'<response_label ident="choice{j}"><material><mattext>{opt}</mattext></material></response_label>'
            )

        resprocessing = (
            f"<resprocessing><respcondition><conditionvar><varequal>choice{correct_idx}</varequal></conditionvar>"
            '<setvar action="Set">100</setvar></respcondition></resprocessing>'
        )

        item = (
            f'<item ident="{item_ident}"><presentation>'
            f"<material><mattext>{q_text}</mattext></material>"
            '<response_lid ident="response1" rcardinality="Single">'
            "<render_choice>"
            + "".join(choices_xml)
            + "</render_choice></response_lid></presentation>"
            + resprocessing
            + "</item>"
        )

    else:
        # Short answer / open question
        ak = template_data.get("answer_key", "")
        if "{{" in ak and "}}" in ak:
            answer = render_with_sample(ak, sample)
        else:
            answer = evaluate_expression(ak, sample)

        item = (
            f'<item ident="{item_ident}"><presentation>'
            f"<material><mattext>{q_text}</mattext></material>"
            '<response_str ident="response1" rcardinality="Single"/>'
            "</presentation>"
            "<resprocessing>"
            f"<respcondition><conditionvar><varequal><![CDATA[{_escape_xml(str(answer))}]]></varequal></conditionvar>"
            '<setvar action="Set">100</setvar></respcondition>'
            "</resprocessing>"
            "</item>"
        )

    return item


def _create_qti_zip(
    samples: List[Dict[str, Any]], question_template: str, template_data: Dict[str, Any]
) -> bytes:
    """Create an in-memory QTI 1.2 zip package containing all items for samples.

    Returns bytes of the zip file ready for upload.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Create items folder and item files
        manifest_resources = []
        for idx, sample in enumerate(samples):
            item_xml = _build_qti_item(idx, sample, question_template, template_data)
            item_path = f"items/item_{idx+1}.xml"
            zf.writestr(
                item_path,
                f'<?xml version="1.0" encoding="UTF-8"?>\n<questestinterop>{item_xml}</questestinterop>',
            )
            res_id = f"RES_{idx+1}"
            manifest_resources.append((res_id, item_path))

        # Build a minimal imsmanifest.xml referencing the item files
        manifest_id = f"man_{uuid.uuid4().hex}"
        resources_xml = []
        for res_id, href in manifest_resources:
            resources_xml.append(
                f'<resource identifier="{res_id}" type="associatedcontent/imsqti_xmlv1p2">\n<file href="{href}"/>\n</resource>'
            )

        manifest = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<manifest identifier="{manifest_id}" xmlns="http://www.imsglobal.org/xsd/ims_qtiasiv1p2">\n'
            "<metadata><schema>IMS QTI</schema></metadata>\n"
            "<organizations/>\n"
            "<resources>\n" + "\n".join(resources_xml) + "\n</resources>\n</manifest>"
        )

        zf.writestr("imsmanifest.xml", manifest)

    buf.seek(0)
    return buf.read()


def _upload_qti_to_canvas(
    qti_bytes: bytes, filename: str = "questions.zip"
) -> Dict[str, Any]:
    """Upload the QTI ZIP directly to Canvas using the content_migrations API."""
    try:
        migration = course.create_content_migration(
            migration_type="qti_converter",
            pre_attachment={"name": filename, "data": qti_bytes},
        )

        if migration is None or migration.get_migration_issues()._has_next():
            return {
                "ok": False,
                "error": str(migration.get_migration_issues()[0]),
            }
        return {"ok": True, "response": str(migration.get_progress())}
    except Exception as e:
        print(e)
        return {"ok": False, "error": str(e)}


def upload_samples_to_canvas(
    bank_id: int,
    samples: List[Dict[str, Any]],
    question_template: str,
    template_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Export samples as QTI and import into Canvas, falling back if necessary.

    Returns a summary dict describing success/failure and any import response.
    """
    results = {"success": 0, "failed": 0, "errors": [], "import_response": None}

    try:
        qti_bytes = _create_qti_zip(samples, question_template, template_data)
    except Exception as e:
        results["failed"] = len(samples)
        results["errors"].append(f"Failed to build QTI package: {str(e)}")
        return results

    upload_result = _upload_qti_to_canvas(qti_bytes)
    if upload_result.get("ok"):
        results["import_response"] = upload_result.get("response")
        results["success"] = len(samples)
        return results
    else:
        # QTI import failed; record error and attempt per-question fallback
        results["errors"].append(f"QTI import failed: {upload_result.get('error')}")

    # Fallback: attempt the previous per-sample question creation behavior
    # (mostly preserved from earlier implementation). We won't attempt to
    # re-verify bank existence here; reuse requester where possible.
    for idx, sample in enumerate(samples):
        try:
            q_text = render_with_sample(question_template, sample)
            q_type = template_data.get("type", "open")

            if q_type == "mc":
                options = [
                    render_with_sample(opt or "", sample)
                    for opt in template_data.get("options", [])
                ]
                correct_idx = template_data.get("correct", 0)

                answers = [
                    {
                        "id": k,
                        "text": opt,
                        "comments": "",
                        "weight": 100 if k == correct_idx else 0,
                        "blank": False,
                    }
                    for k, opt in enumerate(options)
                ]

                question_data = {
                    "question_name": f"Sample {idx + 1}",
                    "question_type": "multiple_choice",
                    "question_text": q_text,
                    "answers": answers,
                }

            elif q_type == "tf":
                correct = template_data.get("correct", "True")
                correct_idx = 0 if correct == "True" else 1
                answers = [
                    {
                        "id": 0,
                        "text": "True",
                        "weight": 100 if correct_idx == 0 else 0,
                        "comments": "",
                    },
                    {
                        "id": 1,
                        "text": "False",
                        "weight": 100 if correct_idx == 1 else 0,
                        "comments": "",
                    },
                ]

                question_data = {
                    "question_name": f"Sample {idx + 1}",
                    "question_type": "true_false",
                    "question_text": q_text,
                    "answers": answers,
                }

            else:
                ak = template_data.get("answer_key", "")
                if "{{" in ak and "}}" in ak:
                    answer = render_with_sample(ak, sample)
                else:
                    answer = evaluate_expression(ak, sample)

                question_data = {
                    "question_name": f"Sample {idx + 1}",
                    "question_type": "short_answer_question",
                    "question_text": q_text,
                    "answers": [
                        {"id": 1, "text": answer, "weight": 100, "comments": ""}
                    ],
                }

            # Attempt to create via raw request to question banks endpoint
            try:
                post_url = (
                    f"/api/v1/courses/{COURSE_CODE}/question_banks/{bank_id}/questions"
                )
                requester.request("POST", post_url, data=question_data)
                results["success"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"Sample {idx + 1}: {str(e)}")

        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"Sample {idx + 1}: {str(e)}")

    return results
