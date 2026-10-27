"""Replace the Gradebook card with SignalProof in the existing portfolio."""
from pathlib import Path
import re
import shutil
import sys


def main():
    if len(sys.argv) != 3:
        sys.exit('Usage: python3 tools/replace_gradebook.py PORTFOLIO_PATH SIGNALPROOF_PATH')

    portfolio = Path(sys.argv[1]).expanduser().resolve()
    signalproof = Path(sys.argv[2]).expanduser().resolve()
    projects = portfolio / 'src/data/projects.ts'
    source_image = signalproof / 'docs/portfolio-signalproof.png'
    target_image = portfolio / 'public/signalproof-dashboard.png'

    if not projects.is_file():
        sys.exit(f'Portfolio projects file not found: {projects}')
    if not source_image.is_file():
        sys.exit(f'Portfolio screenshot missing: {source_image}')

    text = projects.read_text(encoding='utf-8')
    if "id: 'signalproof'" in text:
        print('SignalProof is already listed. No duplicate added.')
        return

    # Keep all other project entries as-is.
    block = re.compile(r"(?ms)^  \{\s*\n(?=\s*id:\s*['\"]gradebook['\"],).*?^  \},?\s*$")
    match = block.search(text)
    if not match:
        sys.exit('Could not find the Gradebook card. No changes made.')

    old = match.group(0)
    number = re.search(r"\bnumber:\s*['\"](\d+)['\"]", old)
    if not number:
        sys.exit('Gradebook card has an unexpected structure. No changes made.')

    new = f"""  {{
    id: 'signalproof',
    number: '{number.group(1)}',
    title: 'SignalProof',
    category: 'Network monitoring and diagnostics',
    description:
      'Built a Python network-monitoring application that records connectivity issues, tracks latency and incident history, and generates evidence reports. The public demo uses sample data; the local agent performs real measurements.',
    highlights: [
      'Connection monitoring and incident history',
      'Manual speed, ping, jitter, and packet-loss checks',
      'Exportable diagnostic reports and interactive demo',
    ],
    tech: ['Python', 'SQLite', 'JavaScript', 'HTML', 'CSS'],
    screenshot: '/signalproof-dashboard.png',
    liveUrl: 'https://rayjim28.github.io/signalproof/',
    repoUrl: 'https://github.com/rayjim28/signalproof',
  }},"""
    updated = text[:match.start()] + new + text[match.end():]
    shutil.copy2(source_image, target_image)
    projects.write_text(updated, encoding='utf-8')
    print('Replaced the Gradebook card with SignalProof.')
    print('Changed:', projects)
    print('Added image:', target_image)
    print('Movie Mania, BudgetWise, and the portfolio design were left alone.')


if __name__ == '__main__':
    main()
