from pydantic import BaseModel, Field


class QualityAssessment(BaseModel):
    relevance_score: int = Field(description="Topic relevance score from 1-10")
    technical_accuracy_score: int = Field(description="Technical Accuracy score from 1-10")
    hallucination_risk: str = Field(description="low, medium, high")
    strengths :  list[str] = Field(default_factory=list)
    weaknesses : list[str] = Field(default_factory=list)
    missing_topics : list[str] = Field(default_factory=list)
    summary : str = Field("Overall evaluation summary")
    overall_score : float | None = Field(description="Overall Blog Quality score from 1-10")