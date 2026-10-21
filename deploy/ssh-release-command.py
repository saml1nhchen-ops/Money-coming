#!/usr/bin/python3
"""Forced SSH command: parse data, never evaluate a remote shell expression."""
import os,re,shlex,sys

def validated_command(text):
 try:args=shlex.split(text)
 except ValueError:raise ValueError('Invalid deployment command') from None
 if len(args)!=8 or args[:3]!=['sudo','-n','/usr/local/sbin/signal-geo-deploy']:raise ValueError('Only the fixed deployment command is allowed')
 image,revision,ident,published,tag=args[3:]
 patterns=[r'ghcr\.io/saml1nhchen-ops/money-coming/backend@sha256:[a-f0-9]{64}',r'[a-f0-9]{40}',r'[1-9][0-9]{0,18}',r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}']
 if any(not re.fullmatch(pattern,value) for pattern,value in zip(patterns,[image,revision,ident,published,tag])):raise ValueError('Invalid deployment identity')
 return ['/usr/bin/sudo','-n','/usr/local/sbin/signal-geo-deploy',image,revision,ident,published,tag]

def main():
 try:command=validated_command(os.environ.get('SSH_ORIGINAL_COMMAND',''))
 except ValueError:print('Only the configured release deployment command is permitted.',file=sys.stderr);return 64
 os.execv(command[0],command)
if __name__=='__main__':sys.exit(main())
