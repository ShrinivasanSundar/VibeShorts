import re
import zlib
import urllib.request
import os

def encode64(data):
    r = ''
    mapping = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_'
    for i in range(0, len(data), 3):
        b0 = data[i]
        b1 = data[i+1] if i+1 < len(data) else 0
        b2 = data[i+2] if i+2 < len(data) else 0
        c0 = b0 >> 2
        c1 = ((b0 & 0x3) << 4) | (b1 >> 4)
        c2 = ((b1 & 0xF) << 2) | (b2 >> 6)
        c3 = b2 & 0x3F
        r += mapping[c0]
        if i + 1 < len(data):
            r += mapping[c1]
        else:
            r += mapping[c1]
            break
        if i + 2 < len(data):
            r += mapping[c2]
            r += mapping[c3]
        else:
            r += mapping[c2]
            break
    return r

def plantuml_encode(text):
    zlibbed = zlib.compress(text.encode('utf-8'), 9)
    deflated = zlibbed[2:-4]
    return encode64(deflated)

with open('VISUAL-README.md', 'r') as f:
    content = f.read()

pattern = re.compile(r'```plantuml\s*\n(@startuml.*?\n@enduml)\s*\n```', re.DOTALL)
matches = list(pattern.finditer(content))
print(f"Total PlantUML blocks found: {len(matches)}")

for i, match in enumerate(matches, 1):
    puml = match.group(1)
    encoded = plantuml_encode(puml.strip())
    url = f"https://www.plantuml.com/plantuml/svg/{encoded}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"Diagram {i}: OK (Status {resp.status}, Content-Type: {resp.headers.get('Content-Type')})")
    except Exception as e:
        print(f"Diagram {i}: ERROR {e}")
