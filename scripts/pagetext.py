#!/usr/bin/python3
import sys,re,html
t=open(sys.argv[1],'rb').read().decode('utf-8','replace')
t=re.sub(r'(?s)<(script|style|head).*?</\1>','',t)
t=re.sub(r'<a[^>]*href="([^"]+)"[^>]*>',r' [\1] ',t)
t=re.sub(r'<[^>]+>','\n',t); t=html.unescape(t)
lines=[l.strip() for l in t.split('\n') if l.strip()]
s='\n'.join(lines)
i=s.find('AI戦略\n'); j=s.find('このページの先頭へ')
print(s[i:j] if i>=0 else s)
