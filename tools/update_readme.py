"""Add the demo link without rewriting the existing project README."""
from pathlib import Path

readme = Path('README.md')
if not readme.is_file():
    raise SystemExit('Run this from your SignalProof project folder.')
text = readme.read_text(encoding='utf-8')
if 'https://rayjim28.github.io/signalproof/' not in text:
    section = '''\n## Browser demo\n\nI put together a public demo so people can explore SignalProof without installing Python. It has sample connection history, incidents, and performance results. The controls let visitors browse example data, but the demo does not run tests against their networks.\n\n[Try the demo](https://rayjim28.github.io/signalproof/)\n\nThe local Python application is the part that measures a real connection and saves its history.\n'''
    readme.write_text(text.rstrip() + '\n' + section, encoding='utf-8')
    print('Added the public demo section to README.md.')
else:
    print('The README already includes the demo link.')
