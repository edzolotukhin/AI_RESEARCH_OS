from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.auth import AuthorizationDep, PrincipalDep, bearer_scheme
from api.dependencies import ReviewQueryServiceDep
from api.mappers.review_mappers import review_to_response
from api.schemas.reviews import ReviewListResponse, ReviewResponse

router = APIRouter(tags=["reviews"])


@router.get(
    "/projects/{project_id}/reviews",
    response_model=ReviewListResponse,
    summary="List durable report reviews for a project",
    operation_id="listProjectReviews",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Project not found."},
    },
)
def list_project_reviews(
    project_id: str,
    review_service: ReviewQueryServiceDep,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
    workflow_run_id: str | None = Query(default=None),
    report_id: str | None = Query(default=None),
    verdict: str | None = Query(default=None),
) -> ReviewListResponse:
    authorization.require_project(principal, project_id)
    reviews = review_service.list_reviews_for_project(
        project_id,
        workflow_run_id=workflow_run_id,
        report_id=report_id,
        verdict=verdict,
    )
    return ReviewListResponse(
        items=[review_to_response(item) for item in reviews],
        count=len(reviews),
    )


@router.get(
    "/reviews/{review_id}",
    response_model=ReviewResponse,
    summary="Get durable report review by id",
    operation_id="getReview",
    dependencies=[Depends(bearer_scheme)],
    responses={
        401: {"description": "Authentication required."},
        404: {"description": "Review not found."},
    },
)
def get_review(
    review_id: str,
    authorization: AuthorizationDep,
    principal: PrincipalDep,
) -> ReviewResponse:
    review, _ = authorization.require_review(principal, review_id)
    return review_to_response(review)
