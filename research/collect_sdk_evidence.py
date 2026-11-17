"""Collect public 2027.2.0-beta1 SDK API signatures; does not start a Gateway.

Usage: python research/collect_sdk_evidence.py --cache /path/to/cache --output /path/to/report.json
Archives remain outside Git. No credentials or third-party implementation source are collected.
"""
import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
import urllib.request
import zipfile

VERSION = '2027.2.0-beta1'
BASE = 'https://nexus.inductiveautomation.com/repository/public/com/inductiveautomation/ignition'
CLASSES = {
    'common': {
        'com/inductiveautomation/ignition/common/ai': ['AiContext', 'AgenticHarness', 'CallableTool', 'AiActor', 'Tools'],
        'com/inductiveautomation/ignition/common/tags/model': ['TagManager', 'TagProvider'],
    },
    'gateway-api': {
        'com/inductiveautomation/ignition/gateway/ai': ['GatewayAiContext'],
        'com/inductiveautomation/ignition/gateway/web/session': ['WebUiSession', 'WebUiSessionManager'],
        'com/inductiveautomation/ignition/gateway/dataroutes': ['RequestContext'],
        'com/inductiveautomation/ignition/gateway/resourcecollection': ['ResourceCollectionManager', 'PartialPushResult'],
        'com/inductiveautomation/ignition/gateway/tags/model': ['GatewayTagManager'],
    },
    'designer': {
        'com/inductiveautomation/ignition/designer/ai': ['DesignerToolFactory'],
        'com/inductiveautomation/ignition/designer/ai/tool': ['DesignableProjectTools', 'DesignerStateTools', 'GatewayConfigTools'],
        'com/inductiveautomation/ignition/designer/ai/embed': ['ReplyRenderer'],
    },
}

class Signatures(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.current = []
        self.signatures = []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            if tag not in {'br', 'wbr', 'hr', 'img', 'input', 'meta', 'link'}:
                self.depth += 1
        elif 'member-signature' in dict(attrs).get('class', '').split():
            self.depth = 1
            self.current = []

    def handle_endtag(self, tag):
        if self.depth and tag not in {'br', 'wbr', 'hr', 'img', 'input', 'meta', 'link'}:
            self.depth -= 1
            if not self.depth:
                self.signatures.append(' '.join(''.join(self.current).split()))

    def handle_data(self, text):
        if self.depth:
            self.current.append(text)


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--cache', type=Path, required=True)
    args.add_argument('--output', type=Path, required=True)
    options = args.parse_args()
    options.cache.mkdir(parents=True, exist_ok=True)
    result = {'version': VERSION, 'evidence_kind': 'public-javadoc-static-inspection',
              'runtime_verified': False, 'artifacts': []}
    for artifact, packages in CLASSES.items():
        url = f'{BASE}/{artifact}/{VERSION}/{artifact}-{VERSION}-javadoc.jar'
        target = options.cache / f'{artifact}-javadoc.jar'
        if not target.exists():
            with urllib.request.urlopen(url, timeout=60) as response:
                target.write_bytes(response.read())
        data = target.read_bytes()
        item = {'artifact': artifact, 'url': url, 'size_bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest(), 'classes': []}
        with zipfile.ZipFile(target) as archive:
            for package, names in packages.items():
                for name in names:
                    entry = f'{package}/{name}.html'
                    parser = Signatures()
                    parser.feed(archive.read(entry).decode('utf-8'))
                    if not parser.signatures:
                        raise ValueError(f'No API signatures extracted from {entry}')
                    item['classes'].append({'qualified_name': f'{package.replace("/", ".")}.{name}',
                                            'archive_entry': entry, 'signatures': parser.signatures})
        result['artifacts'].append(item)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f'Collected {sum(len(a["classes"]) for a in result["artifacts"])} classes from {len(result["artifacts"])} artifacts')

if __name__ == '__main__':
    main()
