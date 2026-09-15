"""Publish one consistent snapshot only after the scraper has succeeded."""
import json
from scraper import ROOT, packed

status = json.loads((ROOT / 'data/status.json').read_text(encoding='utf-8'))
draws = json.loads((ROOT / 'data/results.json').read_text(encoding='utf-8'))
assert len(draws) == status['database_total'] and draws
target = ROOT / 'data/feed.json'
temporary = target.with_suffix('.tmp')
temporary.write_text(packed({'schema':1,'checkedAt':status['checked_at'],'count':len(draws),'draws':draws})+'\n',encoding='utf-8')
temporary.replace(target)
print(f'Published {len(draws)} draws; checked {status["checked_at"]}')
