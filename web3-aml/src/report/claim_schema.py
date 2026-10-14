"""Restricted factual statements. No LLM-authored factual prose or values."""
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

SECTIONS = ('overview','behavior','graph','paths','assessment','limitations')


class Claim(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    claim_id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')
    claim_type: str
    fact_ids: list[str] = Field(min_length=1,max_length=1)
    subject: dict
    unit: str
    wording: str = 'standard'


class Section(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    section: Literal['overview','behavior','graph','paths','assessment','limitations']
    claims: list[Claim]


class ReportDocument(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    schema_version: Literal['report_claims_v1']
    sections: list[Section] = Field(min_length=6,max_length=6)


def empty_document():
    return {'schema_version':'report_claims_v1',
            'sections':[{'section':s,'claims':[]} for s in SECTIONS]}


def blueprint(fact, claim_id=None):
    import copy
    return {'claim_id':claim_id or 'C_'+fact['fact_id'][2:],
        'claim_type':fact['fact_type'],'fact_ids':[fact['fact_id']],
        'subject':copy.deepcopy(fact['subject']),'unit':fact['unit'],'wording':'standard'}
