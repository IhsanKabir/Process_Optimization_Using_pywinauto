import base64
with open('downloads_b64.txt', encoding='utf-16') as f:
    data = f.read().replace('\n','').replace('\r','')
decoded = base64.b64decode(data).decode('utf-8', 'replace')
with open('downloads_page.tsx', 'w', encoding='utf-8') as f:
    f.write(decoded)
print(decoded[:3000])
