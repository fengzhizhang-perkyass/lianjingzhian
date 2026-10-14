"""Validate each statement against the program-owned fact type and subject."""
import copy
from pydantic import ValidationError
from src.report.claim_schema import Claim,SECTIONS,blueprint


def validate_claim(raw,section,catalog):
    try:
        claim = Claim.model_validate(raw).model_dump()
    except ValidationError:
        return None,'SCHEMA_INVALID'
    if len(set(claim['fact_ids']))!=len(claim['fact_ids']):
        return None,'REFERENCE_DUPLICATE'
    fact = catalog.facts.get(claim['fact_ids'][0])
    if fact is None: return None,'REFERENCE_MISSING'
    if claim['claim_type']!=fact['fact_type']: return None,'CLAIM_FACT_TYPE_MISMATCH'
    if claim['subject']!=fact['subject']: return None,'SUBJECT_MISMATCH'
    if claim['unit']!=fact['unit']: return None,'UNIT_MISMATCH'
    if claim['wording'] not in ('standard','brief'): return None,'WORDING_UNSUPPORTED'
    if section!=fact['section']: return None,'SECTION_MISMATCH'
    return claim,None


def validate_document(document,catalog,config):
    catalog.verify()
    errors,valid = [],[]
    if (not isinstance(document,dict) or set(document)!={'schema_version','sections'}
            or document.get('schema_version')!='report_claims_v1' or not isinstance(document.get('sections'),list)):
        return {'structural_error':'DOCUMENT_SCHEMA_INVALID','valid':[],'errors':[]}
    sections = document['sections']
    if (len(sections)!=len(SECTIONS) or any(not isinstance(s,dict) or set(s)!={'section','claims'}
            or s.get('section') not in SECTIONS or not isinstance(s.get('claims'),list) for s in sections)
            or len({s['section'] for s in sections})!=len(SECTIONS)):
        return {'structural_error':'SECTION_SCHEMA_INVALID','valid':[],'errors':[]}
    if sum(len(s['claims']) for s in sections)>config['max_claims']:
        return {'structural_error':'CLAIM_LIMIT_EXCEEDED','valid':[],'errors':[]}
    seen_ids,seen_facts = set(),set()
    for section in sections:
        for position,raw in enumerate(section['claims']):
            claim,code = validate_claim(raw,section['section'],catalog)
            if code is None and claim['claim_id'] in seen_ids: code='CLAIM_ID_DUPLICATE'
            if code is None and claim['fact_ids'][0] in seen_facts: code='FACT_ALREADY_REPORTED'
            if code:
                errors.append({'section':section['section'],'position':position,
                    'claim_id':raw.get('claim_id') if isinstance(raw,dict) else None,
                    'error_code':code,'raw_claim':copy.deepcopy(raw)})
            else:
                seen_ids.add(claim['claim_id']); seen_facts.update(claim['fact_ids'])
                valid.append({'section':section['section'],'claim':claim,'status':'passed'})
    return {'structural_error':None,'valid':valid,'errors':errors}


def canonical_records(catalog,all_facts=False):
    return [{'section':f['section'],'claim':blueprint(f),'status':'template'} for f in catalog.facts.values()
            if f['required'] or all_facts or f['fact_type']=='feature_attribution']
