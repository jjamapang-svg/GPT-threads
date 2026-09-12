"""Read-only capability check. Never logs reply contents or credentials."""
import os
import sys
import requests
from post_threads import Meta, log


def main():
    api=Meta()
    api.identity()
    ready=bool(os.environ.get('OPENAI_API_KEY','').strip())
    log('OPENAI_API_KEY configured: '+str(ready))
    try:
        response=api.session.get('https://graph.threads.net/v1.0/17965602573193805/conversation',params={'fields':'id','limit':1},timeout=(10,30),allow_redirects=False)
    except requests.RequestException:
        raise RuntimeError('Reply permission check transport failure') from None
    log('Reply-read permission check HTTP status: '+str(response.status_code))
    if response.status_code!=200:
        log('Reply read access unavailable: authorize threads_read_replies and threads_manage_replies')
        ready=False
    if not ready:
        raise RuntimeError('Automation prerequisites missing; see checks above')

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        log('ERROR: '+str(exc))
        sys.exit(1)
