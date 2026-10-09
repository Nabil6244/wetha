"""Deterministic event grouping, verification, and editorial priority from source evidence."""
import hashlib
from datetime import datetime, timedelta, timezone
from .contracts import Advisory
from .weather import changes, freshness


class IntelligenceDesk:
    def __init__(self, items: list[Advisory], feeds: list[dict] | None = None, memberships: dict[str, set[str]] | None = None, as_of: datetime | None = None):
        self.items = items
        self.as_of = as_of or datetime.now(timezone.utc)
        self.by_id = {item.id:item for item in items}
        self.feeds = {feed['url']:feed for feed in feeds or []}
        self.memberships = memberships or {}
        parent = {}

        def root(key):
            parent.setdefault(key, key)
            if parent[key] != key:
                parent[key] = root(parent[key])
            return parent[key]

        def join(a, b):
            ra, rb = root(a), root(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

        for item in items:
            if item.provider == 'NWS':
                root(item.id)
                for reference in item.references:
                    join(item.id, reference)
        self.group_keys = {item.id:('NWS:' + root(item.id) if item.provider == 'NWS' else item.provider + ':' + item.event_key) for item in items}
        self.groups = {}
        for item in items:
            self.groups.setdefault(self.group_keys[item.id], []).append(item)
        for group in self.groups.values():
            group.sort(key=lambda item:(item.issued_at, item.id))

    def related(self, item: Advisory) -> list[Advisory]:
        return self.groups[self.group_keys[item.id]]

    def previous(self, item: Advisory) -> Advisory | None:
        return next((prior for prior in reversed(self.related(item)) if prior.issued_at < item.issued_at), None)

    def status(self, item: Advisory) -> str:
        label = freshness(item, self.as_of)
        if label != 'current':
            return label
        siblings = self.related(item)
        if siblings[-1].issued_at > item.issued_at:
            return 'superseded'
        peers = [peer for peer in siblings if peer.issued_at == item.issued_at]
        if len({peer.checksum for peer in peers}) > 1:
            return 'conflicting'
        feed = self.feeds.get(item.source_feed_url)
        if feed:
            if not feed['last_success_at'] or feed['status'] not in ('healthy', 'degraded', 'collecting'):
                return 'stale_feed'
            checked = datetime.fromisoformat(feed['last_success_at'])
            if checked < self.as_of - timedelta(seconds=max(900, feed['interval_seconds'] * 3)):
                return 'stale_feed'
            if item.id not in self.memberships.get(feed['id'], set()):
                return 'not_active'
        return label

    def verification(self, item: Advisory) -> dict:
        status = self.status(item)
        siblings = self.related(item)
        peers = [peer for peer in siblings if peer.issued_at == item.issued_at]
        latest_unambiguous = siblings[-1].issued_at <= item.issued_at and len({peer.checksum for peer in peers}) <= 1
        operational = item.provider != 'NWS' or (item.facts.get('status') == 'Actual' and item.facts.get('message_type') in ('Alert', 'Update'))
        checks = [
            {'check':'Officially fetched source', 'passed':item.provenance == 'official_fetch'},
            {'check':'Timezone-aware issue time', 'passed':item.issued_at.tzinfo is not None},
            {'check':'Operational advisory', 'passed':operational and item.provider != 'TRAINING'},
            {'check':'Current source evidence', 'passed':status == 'current'},
            {'check':'Latest unambiguous event version', 'passed':latest_unambiguous},
        ]
        return {'status':'verified_source' if all(check['passed'] for check in checks) else 'restricted', 'checks':checks,
            'manual_review_required':True, 'confidence_note':'Source provenance and field validation do not verify every meteorological claim. Human review is required.'}

    def priority(self, item: Advisory) -> dict:
        status = self.status(item)
        if status != 'current':
            return {'score':0, 'tier':'restricted', 'reasons':[status.replace('_',' ') + ' evidence is not eligible for current news']}
        severity = {'Extreme':60, 'Severe':45, 'Moderate':25, 'Minor':10, 'Unknown':0}.get(item.severity, 0)
        age = max(0, (self.as_of - item.issued_at).total_seconds() / 3600)
        recency = max(0, 15 - round(age * 2))
        certainty = 5 if item.facts.get('certainty') in ('Observed', 'Likely') else 0
        urgency = 5 if item.facts.get('urgency') == 'Immediate' else 0
        relevant = 10 if item.provider == 'NWS' else 5 if item.warnings else 0
        prior = self.previous(item)
        updated = 5 if prior and prior.provenance == 'official_fetch' and changes(prior, item) else 0
        score = min(100, severity + recency + certainty + urgency + relevant + updated)
        reasons = [(item.severity + ' official CAP severity') if item.provider == 'NWS' else ('Editorial severity from reported wind: ' + str(item.facts.get('wind_mph')) + ' mph'), f'{round(age, 1)} hours since issue']
        if relevant: reasons.append('US alert area' if item.provider == 'NWS' else 'Official watch/warning coverage')
        if updated: reasons.append('Changes detected against stored earlier evidence')
        if certainty: reasons.append('Official certainty: ' + str(item.facts['certainty']))
        return {'score':score, 'tier':'lead' if score >= 70 else 'update' if score >= 40 else 'monitor', 'reasons':reasons}

    def describe(self, item: Advisory) -> dict:
        prior = self.previous(item)
        latest = self.related(item)[-1]
        return {**item.model_dump(mode='json', exclude={'source_payload'}), 'freshness':self.status(item),
            'event_id':'event:' + hashlib.sha256(self.group_keys[item.id].encode()).hexdigest()[:24],
            'previous_id':prior.id if prior else None,
            'superseded_by':latest.id if latest.issued_at > item.issued_at else None,
            'changes':[change.model_dump() for change in changes(prior, item)],
            'comparison':{'status':'verified_sources' if prior and prior.provenance == item.provenance == 'official_fetch' else 'unverified' if prior else 'not_available', 'previous_source_url':prior.source_url if prior else None},
            'verification':self.verification(item), 'priority':self.priority(item)}

    def descriptions(self) -> list[dict]:
        return sorted((self.describe(item) for item in self.items), key=lambda item:(item['priority']['score'], item['issued_at'], item['id']), reverse=True)

    def events(self) -> list[dict]:
        result = []
        for group in self.groups.values():
            latest = group[-1]
            described = self.describe(latest)
            result.append({'id':described['event_id'], 'latest_advisory_id':latest.id, 'title':latest.title, 'provider':latest.provider,
                'status':described['freshness'], 'priority':described['priority'], 'advisory_ids':[item.id for item in group],
                'changes':described['changes'], 'last_issue_at':latest.issued_at.isoformat()})
        return sorted(result, key=lambda event:(event['priority']['score'], event['last_issue_at']), reverse=True)
