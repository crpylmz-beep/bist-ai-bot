"""Code inventory, not a claim about production volume contents."""
import ast
from pathlib import Path
from .records import now

CRITICAL=('gecmis','gecmisi','hafiza','sonuc','snapshot','arsiv','prediction','learning','recovery','pending','alarm','subscription','kullanici','mumlar','signal','ogren')
CACHE=('cache','gecersiz_sembol','durum','heartbeat')


def classify(name):
    value=name.lower()
    if any(word in value for word in CRITICAL):return 'CRITICAL_PRESERVE'
    if any(word in value for word in CACHE):return 'CACHE_REVIEW_ONLY'
    return 'UNKNOWN_PRESERVE'


def code_inventory(root):
    rows={}
    for path in sorted(Path(root).glob('*.py')):
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value.endswith('.json') and '\n' not in node.value and len(node.value)<200:
                name=node.value;entry=rows.setdefault(name,{'name':name,'classification':classify(name),'references':[]})
                entry['references'].append({'module':path.name,'line':node.lineno})
    return {'scope':'REPOSITORY_CODE_ONLY','production_inspected':False,'generated_at':now(),'json_references':list(rows.values())}
