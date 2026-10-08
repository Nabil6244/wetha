"""Conservative paragraph-level claim tracking and explicit human source attestations."""
import copy
import hashlib
import re
from .contracts import Advisory
from .newsroom import GroundedScriptWriter
from .storage import now


def normalized(text: str) -> str:
    return ' '.join(text.split())


def claim_id(text: str) -> str:
    return 'claim:' + hashlib.sha256(normalized(text).encode()).hexdigest()[:24]


def numbers(text: str) -> set[str]:
    return set(re.findall(r'(?<!\w)-?\d+(?:\.\d+)?', text))


def blocks_for(document: dict, evidence: list[Advisory], previous_claims=()) -> list[dict]:
    prior = {normalized(claim['text']):claim for claim in previous_claims}
    generated = {normalized(part) for scene in document.get('grounded_scenes', document['scenes']) for part in scene['script_segment'].split('\n\n') if part.strip()}
    result = []
    for paragraph in document['text'].split('\n\n'):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        key = normalized(paragraph)
        old = prior.get(key)
        if old:
            retained = copy.deepcopy(old)
            retained['text'] = paragraph
            result.append(retained)
            continue
        quoted = [item.id for item in evidence if key in normalized(item.text)]
        result.append({'id':claim_id(paragraph), 'text':paragraph,
            'status':'generated_grounded' if key in generated else 'source_quote' if quoted else 'requires_verification',
            'source_advisory_ids':quoted or [item.id for item in evidence], 'support':None})
    return result


def prepare(document: dict, evidence: list[Advisory]) -> dict:
    document['grounded_scenes'] = copy.deepcopy(document['scenes'])
    document['claims'] = blocks_for(document, evidence)
    document['evidence_manifest'] = [{'id':item.id, 'checksum':item.checksum, 'source_url':item.source_url,
        'issued_at':item.issued_at.isoformat(), 'expires_at':item.expires_at.isoformat() if item.expires_at else None,
        'provenance':item.provenance} for item in evidence]
    document['revision'] = 1
    return document


def edited(document: dict, text: str, evidence: list[Advisory]) -> dict:
    result = copy.deepcopy(document)
    result['text'] = '\n\n'.join(part.strip() for part in text.split('\n\n') if part.strip())
    if result['text'] == document['text']:
        raise ValueError('No text changes to save.')
    result['claims'] = blocks_for(result, evidence, document.get('claims', []))
    reset_review(result)
    rebuild_scenes(result)
    return result


def reset_review(document: dict):
    document.update(status='needs_review', review_required=True, broadcast_eligible=False)
    for name in ('reviewer', 'reviewed_at', 'review_note'):
        document.pop(name, None)
    for check in document['qc']:
        if check['check'] == 'Human editorial review':
            check['passed'] = False


def rebuild_scenes(document: dict):
    template = document['grounded_scenes'][0]
    document['scenes'] = [{**copy.deepcopy(template), 'id':f'scene-{i+1}', 'script_segment':claim['text'],
        'target_seconds':round(len(claim['text'].split()) / 145 * 60, 1), 'claim_id':claim['id']} for i, claim in enumerate(document['claims'])]
    document['estimated_seconds'] = round(len(document['text'].split()) / 145 * 60)


def attest(document: dict, body, evidence: list[Advisory]) -> dict:
    result = copy.deepcopy(document)
    claim = next((claim for claim in result['claims'] if claim['id'] == body.claim_id), None)
    if not claim:
        raise KeyError(body.claim_id)
    item = next((item for item in evidence if item.id == body.advisory_id), None)
    if not item:
        raise ValueError('Support must cite evidence already included in this script package.')
    quote = normalized(body.quote)
    if quote not in normalized(item.text):
        raise ValueError('The support quote must match the preserved source text exactly (whitespace may vary).')
    if numbers(claim['text']) - numbers(quote):
        raise ValueError('The edited claim includes numerical values missing from the cited quote. Correct the claim or provide its complete numerical support.')
    claim.update(status='human_attested', source_advisory_ids=[item.id], support={
        'quote':body.quote.strip(), 'explanation':body.explanation.strip(), 'reviewer':body.reviewer.strip(),
        'advisory_id':item.id, 'checksum':item.checksum, 'attested_at':now(),
        'note':'Human assessment of meaning; quote and numeric presence checks are not automated semantic verification.'})
    reset_review(result)
    return result


def evaluate(document: dict, intelligence, evidence: list[Advisory], review=None) -> dict:
    result = copy.deepcopy(document)
    primary = evidence[0]
    label = intelligence.status(primary)
    official = all(item.provenance == 'official_fetch' for item in evidence)
    if label == 'current' and not official:
        label = 'unverified'
    result['label'] = label
    manifest = result.get('evidence_manifest', [])
    unchanged = all(any(item.id == row['id'] and item.checksum == row['checksum'] for item in evidence) for row in manifest)
    claims = result.get('claims', [])
    covered = bool(claims) and all(claim['status'] != 'requires_verification' for claim in claims)
    # An edited or model-composed document must retain its fixed safety opening.
    opening = normalized(result['grounded_scenes'][0]['script_segment']) if result.get('grounded_scenes') else ''
    safety = not opening or (bool(claims) and normalized(claims[0]['text']) == opening)
    current = label == 'current'
    valid_review = bool(review and review['revision'] == result.get('revision', 1) and current and official and unchanged and covered and safety)
    checks = [
        {'check':'Source provenance', 'passed':official}, {'check':'Source freshness', 'passed':current},
        {'check':'Evidence checksums', 'passed':unchanged}, {'check':'Claim support', 'passed':covered},
        {'check':'Opening source context', 'passed':safety}, {'check':'Human editorial review', 'passed':valid_review},
        {'check':'Audio and rendered video', 'passed':False},
    ]
    result['qc'] = checks
    issues = []
    for claim in claims:
        if claim['status'] == 'requires_verification':
            issues.append({'code':'unsupported_claim', 'blocking':True, 'claim_id':claim['id'], 'message':'Edited prose requires a named source attestation with an exact supporting quote.'})
        if claim['status'] == 'human_attested':
            issues.append({'code':'human_attestation', 'blocking':False, 'claim_id':claim['id'], 'message':'Meaning was assessed by a named human; automated checks do not prove semantic correctness.'})
    if not safety:
        issues.append({'code':'missing_context', 'blocking':True, 'message':'Restore the original opening source context before review.'})
    if len({normalized(claim['text']) for claim in claims}) < len(claims):
        issues.append({'code':'repetition', 'blocking':False, 'message':'Repeated paragraphs need an editorial check.'})
    if not 30 <= result['estimated_seconds'] <= 300:
        issues.append({'code':'timing', 'blocking':False, 'message':'Estimated narration is outside 30 seconds to 5 minutes. Audio duration has not been measured.'})
    issues.append({'code':'forecast_uncertainty', 'blocking':False, 'message':'Retain official forecast qualifiers; observed measurements do not establish future conditions.'})
    if not current:
        issues.append({'code':'source_restricted', 'blocking':True, 'message':'Current-news review is blocked: ' + label.replace('_', ' ')})
    if not official or not unchanged:
        issues.append({'code':'evidence_restricted', 'blocking':True, 'message':'All source evidence must retain official provenance and original checksums.'})
    result['editorial'] = {'issues':issues, 'can_review':current and official and unchanged and covered and safety,
        'high_impact':primary.severity in ('Extreme', 'Severe') or bool(primary.warnings),
        'human_review_required':True, 'timing_basis':'145 words/minute estimate; audio not generated',
        'claim_validation':'Generated blocks are source-grounded; free edits require explicit human quote-based verification.'}
    result['review_valid'] = valid_review
    result['status'] = 'reviewed' if valid_review else 'review_invalidated' if review else 'needs_review'
    result['review_required'] = not valid_review
    result['broadcast_eligible'] = False
    return result


def legacy_document(document: dict, evidence: list[Advisory]) -> dict:
    if 'claims' in document:
        return document
    # Old scripts retain their exact text and scenes, but acquire source tracking conservatively.
    result = copy.deepcopy(document)
    baseline = GroundedScriptWriter().generate(evidence[0], evidence[1] if len(evidence) > 1 else None, document.get('label'))
    result['grounded_scenes'] = baseline['scenes']
    result['claims'] = blocks_for(result, evidence)
    result['evidence_manifest'] = [{'id':item.id, 'checksum':item.checksum, 'source_url':item.source_url,
        'issued_at':item.issued_at.isoformat(), 'expires_at':item.expires_at.isoformat() if item.expires_at else None,
        'provenance':item.provenance} for item in evidence]
    result.setdefault('revision', 1)
    return result
