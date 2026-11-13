import json, sys
from collections import Counter

path = sys.argv[1]
d = json.load(open(path))

print('Total sections:', len(d['sections']))
c = Counter(s.get('section_type') for s in d['sections'])
print('Section type distribution:')
for k, v in c.most_common():
    print(f'  {k:25s} {v}')
print()

print('Sample mid-document section (index 10):')
s = d['sections'][10]
print('  page =', s.get('page'))
print('  type =', s.get('section_type'))
print('  text[:300] =', repr(s.get('text', '')[:300]))
