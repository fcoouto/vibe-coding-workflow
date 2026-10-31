#!/usr/bin/env python3
"""One stateless, tool-free Council request; the worker runner owns its lifetime."""
import argparse
import json
import math
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

PACKAGE = Path(__file__).resolve().parents[1]
if str(PACKAGE) not in sys.path: sys.path.insert(0, str(PACKAGE))
from runtime import council_snapshot as snapshot, onboarding
from scripts.openrouter_workers import LIMIT, safe_failure, terminal_failure

ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'
REPORT_LIMIT = 128 * 1024
INPUT_LIMIT = 40 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _payload(payload):
    required = {'model', 'messages', 'provider', 'max_tokens', 'stream'}
    if (not isinstance(payload, dict) or not required <= set(payload)
            or set(payload) - required - {'reasoning'}
            or not isinstance(payload['model'], str) or not re.fullmatch(r'[\w.-]+/[\w./:-]+', payload['model'])
            or payload['model'].lower().endswith(':free') or payload['model'].lower() == 'openrouter/free'
            or payload['stream'] is not False or type(payload['max_tokens']) is not int
            or not 1 <= payload['max_tokens'] <= 2**31 - 1):
        raise ValueError()
    provider = payload['provider']
    if (not isinstance(provider, dict) or set(provider) != {'only', 'allow_fallbacks', 'require_parameters'}
            or provider['allow_fallbacks'] is not False or provider['require_parameters'] is not True
            or not isinstance(provider['only'], list) or len(provider['only']) != 1
            or not isinstance(provider['only'][0], str) or not re.fullmatch(r'[\w./:-]+', provider['only'][0])):
        raise ValueError()
    if 'reasoning' in payload and (not isinstance(payload['reasoning'], dict)
            or set(payload['reasoning']) != {'effort'}
            or payload['reasoning']['effort'] not in ('minimal', 'low', 'medium', 'high', 'xhigh', 'max')):
        raise ValueError()
    messages = payload['messages']
    if (not isinstance(messages, list) or len(messages) != 1
            or any(not isinstance(item, dict) or set(item) != {'role', 'content'}
                   or item['role'] != 'user' or not isinstance(item['content'], str)
                   for item in messages)):
        raise ValueError()
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()
    if len(raw) > INPUT_LIMIT: raise ValueError()
    return raw


def send(payload: dict, auth_data: Path, timeout: float) -> dict:
    result = dict(response='', generation_id=None, reported_model=None, reported_tokens={},
        reported_cost_usd=None, known_cost_subtotal_usd=0, accounting_complete=False, failure=None)
    try:
        raw = _payload(payload)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0: raise ValueError()
    except (ValueError, TypeError, RecursionError):
        return dict(result, failure=dict(category='invalid_request'))
    try:
        snapshot._canonical(auth_data)
        snapshot._directory(auth_data, private=True)
        snapshot._directory(auth_data / 'opencode', private=True)
        record = json.loads(onboarding._read_file(auth_data / 'opencode/auth.json', 128 * 1024, private=True))
        record = record.get('openrouter') if isinstance(record, dict) else None
        if (not isinstance(record, dict) or record.get('type') != 'api'
                or not isinstance(record.get('key'), str) or not record['key'].strip()
                or len(record['key']) > 16000 or any(not 33 <= ord(char) <= 126 for char in record['key'])):
            raise ValueError()
        key = record['key']
    except (OSError, ValueError, TypeError, RecursionError):
        return dict(result, failure=dict(category='authentication'))
    try:
        request = urllib.request.Request(ENDPOINT, data=raw,
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
        # Environment proxy and key overrides must not change the saved destination or credentials.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            body = response.read(LIMIT + 1)
        if len(body) > LIMIT: raise ValueError('output_limit')
        value = json.loads(body)
        if not isinstance(value, dict): raise ValueError()
        if 'error' in value:
            error = value['error']
            code = error.get('code') if isinstance(error, dict) else None
            return dict(result, failure=terminal_failure(dict(data=dict(
                statusCode=code, responseBody=json.dumps({'error': error})[:16384]))))
        for source, target in (('id', 'generation_id'), ('model', 'reported_model')):
            observed = value.get(source)
            if isinstance(observed, str) and re.fullmatch(r'[\w./:-]{1,256}', observed): result[target] = observed
        usage = value.get('usage')
        if isinstance(usage, dict):
            result['reported_tokens'] = {name: usage[name] for name in
                ('prompt_tokens', 'completion_tokens', 'total_tokens') if _number(usage.get(name))}
            if _number(usage.get('cost')):
                result.update(reported_cost_usd=usage['cost'], known_cost_subtotal_usd=usage['cost'])
            result['accounting_complete'] = (result['reported_cost_usd'] is not None
                and all(name in result['reported_tokens'] for name in ('prompt_tokens', 'completion_tokens', 'total_tokens')))
        choices = value.get('choices')
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict): raise ValueError()
        choice = choices[0]
        message = choice.get('message')
        if not isinstance(message, dict): raise ValueError()
        if message.get('tool_calls') or message.get('function_call'):
            return dict(result, failure=dict(category='runtime_or_output', reason='unexpected_tool'))
        reason = choice.get('finish_reason')
        content = message.get('content')
        if reason != 'stop' or not isinstance(content, str) or not content.strip():
            failure = dict(category='policy' if reason in ('content_filter', 'content-filter') else 'incomplete_output')
            if reason in ('length', 'stop', 'content_filter', 'content-filter'): failure['terminal_reason'] = reason
            return dict(result, failure=failure)
        if len(content.encode()) > REPORT_LIMIT: raise ValueError('council_report_limit')
        result['response'] = content
        return result
    except urllib.error.HTTPError as error:
        # Do not expose provider bodies, redirect locations, headers, or exception text.
        try:
            body = error.read(16385)
            failure = terminal_failure(dict(data=dict(statusCode=error.code,
                responseBody=body.decode('utf-8') if len(body) <= 16384 else None)))
        except (OSError, ValueError):
            failure = terminal_failure(dict(data=dict(statusCode=error.code)))
        finally:
            error.close()
        return dict(result, failure=failure)
    except (TimeoutError, urllib.error.URLError, OSError):
        return dict(result, failure=dict(category='transport'))
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        failure = dict(category='runtime_or_output')
        if str(error) in ('output_limit', 'council_report_limit'): failure['reason'] = str(error)
        return dict(result, failure=failure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auth-data', type=Path, required=True)
    parser.add_argument('--timeout', type=float, required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(INPUT_LIMIT + 1)
        if len(raw) > INPUT_LIMIT: raise ValueError()
        result = send(json.loads(raw), args.auth_data, args.timeout)
    except (ValueError, TypeError, OSError, RecursionError):
        result = dict(response='', failure=dict(category='invalid_request'))
    if result['failure'] is not None: result['failure'] = safe_failure(result['failure'])
    print(json.dumps(result, allow_nan=False, separators=(',', ':')), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
