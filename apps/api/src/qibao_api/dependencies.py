from fastapi import Request

from qibao_api.shangshu.pipeline import ResearchPipeline


def get_pipeline(request: Request) -> ResearchPipeline:
    return request.app.state.pipeline

