"""Canvas LMS Integration for question banks."""

import json
from typing import Any, Dict, List

from canvasapi import Canvas
from canvasapi import requester as canvas_requester

from config import CANVAS_TOKEN, CANVAS_URL, COURSE_CODE, TEST_BANK_ID
from utils import evaluate_expression, render_with_sample

canvas = Canvas(CANVAS_URL, CANVAS_TOKEN)
course = canvas.get_course(COURSE_CODE)
requester = canvas_requester.Requester(CANVAS_URL, CANVAS_TOKEN)


def upload_samples_to_canvas(
    bank_id: int,
    samples: List[Dict[str, Any]],
    question_template: str,
    template_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Upload all samples as questions to a Canvas question bank.

    Returns summary of uploaded questions.
    """
    results = {
        "success": 0,
        "failed": 0,
        "errors": [],
    }

    # Try to obtain a bank object if the Canvas client exposes a helper.
    # If not available, verify the bank exists by a raw GET and fall back to
    # using the raw POST endpoint to create questions.
    bank_obj = None
    print(dir(canvas))
    try:
        # Verify bank exists via raw request
        requester.request("GET", f"/api/v1/assessment_question_banks/{bank_id}")
    except Exception as e:
        results["errors"].append(f"Cannot access question bank {bank_id}: {str(e)}")
        results["failed"] = len(samples)
        return results

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

            else:  # open (essay/short answer)
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
                        {
                            "id": 1,
                            "text": answer,
                            "weight": 100,
                            "comments": "",
                        }
                    ],
                }

            # If we have a bank object with a `create_question` helper, use it.
            if bank_obj is not None and hasattr(bank_obj, "create_question"):
                bank_obj.create_question(question_data)
            else:
                # Fallback: call the REST endpoint directly. Use the
                # assessment_question_banks POST questions endpoint.
                # The canvasapi request helper expects params/data as a dict.
                canvas._requester.request(
                    "POST",
                    f"/api/v1/assessment_question_banks/{bank_id}/questions",
                    data=question_data,
                )
            results["success"] += 1

        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"Sample {idx + 1}: {str(e)}")

    return results
    return results
