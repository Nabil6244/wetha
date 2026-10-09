"""Six deterministic newsroom roles with typed JSON handoffs and durable activity."""
import asyncio
import copy
from typing import Literal
from pydantic import BaseModel, ConfigDict
from .contracts import Advisory, Change
from .editorial import prepare, evaluate, rebuild_scenes
from .intelligence import IntelligenceDesk
from .models import compose
from .newsroom import GroundedScriptWriter
from .storage import now


class Packet(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['1'] = '1'


class EvidencePacket(Packet):
    selected_advisory_ids: list[str] = []
    as_of: str
    advisories: list[Advisory]
    feeds: list[dict]
    source_refresh: list[dict]


class ChangePacket(Packet):
    topics: list[dict] = []
    advisory_id: str
    previous_id: str | None
    comparison: dict
    changes: list[Change]


class PriorityPacket(Packet):
    topics: list[dict] = []
    advisory_id: str
    event_id: str
    priority: dict


class VerificationPacket(Packet):
    topics: list[dict] = []
    advisory_id: str
    status: str
    checks: list[dict]
    evidence_manifest: list[dict]


class WritingPacket(Packet):
    script_id: str
    engine: str
    text: str
    claims: list[dict]
    estimated_seconds: int


class EditorialPacket(Packet):
    script_id: str
    qc: list[dict]
    editorial: dict
    broadcast_eligible: Literal[False] = False


class WeatherDataCollector:
    name = 'Data collector'

    async def run(self, store, collector, request) -> EvidencePacket:
        results = []
        ids = request.advisory_ids or [request.advisory_id]
        if request.refresh_sources:
            feeds = {store.advisory(identity).provider.lower() for identity in ids}
            if not feeds <= {'nws', 'nhc'}:
                raise ValueError('Training evidence has no official feed to refresh.')
            for feed in sorted(feeds):
                results.append(await collector.refresh(feed))
        intelligence = IntelligenceDesk(store.advisories(), store.feeds(), store.memberships())
        preserved = {}
        for identity in ids:
            primary = intelligence.by_id[identity]
            preserved[primary.id] = primary
            prior = intelligence.previous(primary)
            if prior:
                preserved[prior.id] = prior
        # Selected order is independent of comparison evidence order.
        return EvidencePacket(as_of=now(), selected_advisory_ids=ids, advisories=list(preserved.values()), feeds=store.feeds(), source_refresh=results)


class ChangeDetector:
    name = 'Change detector'

    def run(self, evidence: EvidencePacket, intelligence) -> ChangePacket:
        described = intelligence.describe(evidence.advisories[0])
        return ChangePacket(advisory_id=described['id'], previous_id=described['previous_id'], comparison=described['comparison'], changes=described['changes'], topics=[{k: intelligence.describe(intelligence.by_id[identity])[k] for k in ('id','previous_id','comparison','changes')} for identity in evidence.selected_advisory_ids])


class NewsPrioritizer:
    name = 'News prioritizer'

    def run(self, evidence: EvidencePacket, intelligence) -> PriorityPacket:
        described = intelligence.describe(evidence.advisories[0])
        return PriorityPacket(advisory_id=described['id'], event_id=described['event_id'], priority=described['priority'], topics=[{k: intelligence.describe(intelligence.by_id[identity])[k] for k in ('id','event_id','priority')} for identity in evidence.selected_advisory_ids])


class FactVerifier:
    name = 'Fact verifier'

    def run(self, evidence: EvidencePacket, intelligence) -> VerificationPacket:
        primary = evidence.advisories[0]
        checked = intelligence.verification(primary)
        manifest = [{'id':item.id, 'checksum':item.checksum, 'source_url':item.source_url, 'issued_at':item.issued_at.isoformat(),
            'expires_at':item.expires_at.isoformat() if item.expires_at else None, 'provenance':item.provenance} for item in evidence.advisories]
        topics = [{'advisory_id':identity, **intelligence.verification(intelligence.by_id[identity])} for identity in evidence.selected_advisory_ids]
        checks = [{'check': (identity + ': ' if len(evidence.selected_advisory_ids) > 1 else '') + check['check'], 'passed':check['passed']} for identity in evidence.selected_advisory_ids for check in intelligence.verification(intelligence.by_id[identity])['checks']] + [{'check':'Official comparison evidence', 'passed':all(item.provenance == 'official_fetch' for item in evidence.advisories)}]
        return VerificationPacket(advisory_id=primary.id, status='verified_source' if all(row['passed'] for row in checks) else 'restricted', checks=checks, evidence_manifest=manifest, topics=topics)


class AIScriptwriter:
    name = 'Scriptwriter'

    async def run(self, evidence: EvidencePacket, intelligence, engine, model_transport=None):
        ids = evidence.selected_advisory_ids or [evidence.advisories[0].id]
        documents = []
        for identity in ids:
            primary = intelligence.by_id[identity]
            prior = intelligence.previous(primary)
            sources = [primary] + ([prior] if prior else [])
            part = prepare(GroundedScriptWriter().generate(primary, prior, intelligence.status(primary)), sources)
            for claim in part['claims']:
                claim['primary_advisory_id'] = identity
            for scene in part['grounded_scenes']:
                scene['parameters']['source_advisory_id'] = identity
            documents.append(part)
        document = documents[0]
        if len(documents) > 1:
            document = copy.deepcopy(document)
            document['title'] = f"Weather roundup · {len(ids)} topics"
            document['selected_advisory_ids'] = ids
            document['chapters'] = [{'advisory_id':identity, 'title':intelligence.by_id[identity].title, 'area':intelligence.by_id[identity].area} for identity in ids]
            document['claims'] = []
            document['grounded_scenes'] = []
            by_text = {}
            for part in documents:
                document['grounded_scenes'].extend(part['grounded_scenes'])
                for claim in part['claims']:
                    if claim['text'] in by_text:
                        retained = by_text[claim['text']]
                        retained['source_advisory_ids'] = list(dict.fromkeys(retained['source_advisory_ids'] + claim['source_advisory_ids']))
                    else:
                        by_text[claim['text']] = claim
                        document['claims'].append(claim)
            closing = documents[0]['claims'][-1]['text']
            document['claims'].sort(key=lambda claim: claim['text'] == closing)
            document['source_advisory_ids'] = [item.id for item in evidence.advisories]
            document['source_refs'] = list(dict.fromkeys(item.source_url for item in evidence.advisories))
            document['evidence_manifest'] = [{'id':item.id,'checksum':item.checksum,'source_url':item.source_url,'issued_at':item.issued_at.isoformat(),'expires_at':item.expires_at.isoformat() if item.expires_at else None,'provenance':item.provenance} for item in evidence.advisories]
            document['text'] = '\n\n'.join(claim['text'] for claim in document['claims'])
        if engine != 'deterministic':
            # Compose only unique catalogue blocks. Duplicates cannot be selected ambiguously.
            if len({block['id'] for block in document['claims']}) != len(document['claims']):
                raise ValueError('Repeated source paragraphs must be resolved before model composition.')
            order = await compose(engine, document['claims'], model_transport)
            catalogue = {claim['id']:claim for claim in document['claims']}
            document['claims'] = [catalogue[identity] for identity in order]
            document['text'] = '\n\n'.join(claim['text'] for claim in document['claims'])
            document['engine'] = engine + '-grounded-composition-v1'
        rebuild_scenes(document)
        output = WritingPacket(script_id=document['id'], engine=document['engine'], text=document['text'], claims=document['claims'], estimated_seconds=document['estimated_seconds'])
        return document, output


class EditorialQualityController:
    name = 'Editorial controller'

    def run(self, document, evidence, intelligence):
        result = evaluate(document, intelligence, evidence.advisories)
        return result, EditorialPacket(script_id=result['id'], qc=result['qc'], editorial=result['editorial'])


class Newsroom:
    def __init__(self, store, collector, model_transport=None):
        self.store, self.collector, self.model_transport = store, collector, model_transport

    async def run(self, request) -> dict:
        for identity in request.advisory_ids or [request.advisory_id]:
            self.store.advisory(identity)  # Validate every selection before creating a run.
        identity = self.store.start_run(request.advisory_id, request.engine)
        job = self.store.start_job('newsroom')
        sequence = 0

        async def step(agent, input_document, action):
            nonlocal sequence
            sequence += 1
            self.store.start_step(identity, sequence, agent.name, input_document)
            result = action()
            if hasattr(result, '__await__'):
                result = await result
            output = result[-1] if isinstance(result, tuple) else result
            self.store.finish_step(identity, sequence, output.model_dump(mode='json'))
            return result

        try:
            evidence = await step(WeatherDataCollector, request.model_dump(), lambda:WeatherDataCollector().run(self.store, self.collector, request))
            intelligence = IntelligenceDesk(self.store.advisories(), evidence.feeds, self.store.memberships())
            evidence_json = evidence.model_dump(mode='json')
            changed = await step(ChangeDetector, evidence_json, lambda:ChangeDetector().run(evidence, intelligence))
            priority = await step(NewsPrioritizer, {'evidence':evidence_json, 'changes':changed.model_dump(mode='json')}, lambda:NewsPrioritizer().run(evidence, intelligence))
            verified = await step(FactVerifier, evidence_json, lambda:FactVerifier().run(evidence, intelligence))
            package = {'evidence':evidence_json, 'changes':changed.model_dump(mode='json'), 'priority':priority.model_dump(mode='json'), 'verification':verified.model_dump(mode='json')}
            document, writing = await step(AIScriptwriter, package, lambda:AIScriptwriter().run(evidence, intelligence, request.engine, self.model_transport))
            document['run_id'] = identity
            # Re-read current feed/evidence state after any slow model request.
            intelligence = IntelligenceDesk(self.store.advisories(), self.store.feeds(), self.store.memberships())
            document, editorial = await step(EditorialQualityController, writing.model_dump(mode='json'), lambda:EditorialQualityController().run(document, evidence, intelligence))
            self.store.finish_run(identity, document)
            self.store.finish_job(job, 'succeeded', 'Six newsroom roles completed; draft requires named human review')
            return document
        except (Exception, asyncio.CancelledError) as error:
            # Never persist provider exception text: it can contain request URLs or credentials.
            message = 'Newsroom interrupted' if isinstance(error, asyncio.CancelledError) else str(error) if isinstance(error, ValueError) and not hasattr(error, 'errors') else type(error).__name__ + ': newsroom stage failed; inspect configuration and source status'
            if sequence:
                self.store.finish_step(identity, sequence, error=message)
            self.store.finish_run(identity, error=message)
            self.store.finish_job(job, 'failed', message)
            if isinstance(error, (ValueError, KeyError, asyncio.CancelledError)):
                raise
            raise ValueError(message) from None
