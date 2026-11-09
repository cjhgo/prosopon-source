import json, os, html
m=json.load(open('out/manifest.json'))
groups={'book':[],'film':[],'music':[]}
for x in m:
    if x.get('cover') and x.get('status') in ('matched','review'):
        groups.setdefault(x['type'],[]).append(x)
for k in groups: groups[k]=groups[k][:8]

def src(x):
    return 'sanjing-covers/'+x['cover'].split('covers/',1)[1]

def book(x,i=None):
    return f'''<figure class="book"><div class="bcover"><img src="{src(x)}" loading="lazy" alt="{html.escape(x['title'])}"></div><figcaption><b>{html.escape(x['title'])}</b><span>{html.escape(x.get('creator',''))}</span></figcaption></figure>'''

def film(x,i):
    return f'''<figure class="sleeve" style="--rot:{'-1.1deg' if i%2==0 else '0.9deg'}"><div class="perf"></div><div class="poster"><img src="{src(x)}" loading="lazy" alt="{html.escape(x['title'])}"></div><div class="flabel"><b>{html.escape(x['title'])}</b><span>{html.escape(x.get('creator',''))}</span></div></figure>'''

def tape(x,i):
    return f'''<figure class="cassette" style="--rot:{'-0.8deg' if i%2==0 else '0.6deg'}"><div class="clabel"><img src="{src(x)}" loading="lazy" alt="{html.escape(x['title'])}"></div><div class="ctitle"><b>{html.escape(x['title'])}</b><span>{html.escape(x.get('creator',''))}</span></div><div class="reels"><i></i><i></i></div><div class="notch"></div></figure>'''

def rows(items, fn, per=4):
    out=[]
    for r in range(0,len(items),per):
        chunk=items[r:r+per]
        out.append(''.join(fn(x,i) for i,x in enumerate(chunk)))
    return out

brows=rows(groups['book'],book)
frows=rows(groups['film'],film)
mrows=rows(groups['music'],tape)

def bookcase():
    parts=[]
    for row in brows:
        parts.append(f'<div class="book-row">{row}</div><div class="shelf"></div>')
    return '<div class="bookcase">'+''.join(parts)+'</div>'
def binder():
    parts=[]
    for row in frows:
        parts.append(f'<div class="film-row">{row}</div>')
    return '<div class="film-binder"><div class="film-head"><span>35 mm</span><span>CONTACT SHEET</span><span>ARCHIVE</span></div>'+''.join(parts)+'</div>'
def rack():
    parts=[]
    for row in mrows:
        parts.append(f'<div class="cassette-row">{row}</div>')
    return '<div class="cassette-rack">'+''.join(parts)+'<div class="rack-rail"></div></div>'

css='''
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=Inter:wght@400;500&display=swap');
:root{--paper:#f3efe5;--ink:#1e2a2b;--muted:#72756a;--line:#d3caba;--celadon:#2f8296;--ochre:#b3763a}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,-apple-system,"Helvetica Neue",Arial,sans-serif}
body::before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.24;background-image:radial-gradient(rgba(30,42,43,.05) 1px,transparent 1px);background-size:4px 4px}
.wrap{max-width:1240px;margin:0 auto;padding:54px 34px 90px;position:relative}
.mast{display:flex;align-items:flex-end;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:18px}
h1{font-family:"Cormorant Garamond",Georgia,serif;font-weight:500;font-size:62px;letter-spacing:.14em;margin:0;line-height:.9}
.kicker{font-size:10px;letter-spacing:.22em;text-transform:uppercase;color:var(--muted);margin:11px 0 0}
.seal{writing-mode:vertical-rl;font-family:"Songti SC",serif;font-size:14px;letter-spacing:.34em;color:var(--celadon);border:1px solid var(--celadon);padding:9px 5px;line-height:1;opacity:.9}
.index{display:flex;gap:30px;padding:16px 0 0;font-size:10px;letter-spacing:.2em;text-transform:uppercase;color:var(--muted)}
.index a{color:inherit;text-decoration:none;border-bottom:1px solid transparent;padding-bottom:2px}
.index a:hover{color:var(--celadon);border-color:var(--celadon)}
section{padding:48px 0 30px;border-bottom:1px solid var(--line)}
section:last-of-type{border-bottom:0}
.head{display:flex;align-items:baseline;gap:16px;margin-bottom:20px}
.head .n{font-family:"Cormorant Garamond",serif;font-size:15px;letter-spacing:.12em;color:var(--ochre);min-width:30px}
.head h2{font-family:"Cormorant Garamond",serif;font-weight:500;font-size:34px;letter-spacing:.16em;margin:0}
.head .d{margin-left:auto;font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
/* BOOKS: wooden bookcase */
.bookcase{position:relative;padding:26px 30px 0;background:linear-gradient(180deg,#3a261b,#24170f);border:12px solid #4a3527;border-top-width:16px;border-bottom-width:20px;box-shadow:0 30px 60px -46px #0008,inset 0 0 60px #0007}
.bookcase::after{content:"";position:absolute;inset:0;background:linear-gradient(118deg,rgba(255,255,255,.10),transparent 34%,rgba(255,255,255,.03) 58%,transparent 72%);pointer-events:none;z-index:5}
.book-row{display:flex;align-items:flex-end;justify-content:center;gap:16px;min-height:242px;padding:0 10px;position:relative;z-index:2}
.book{margin:0;flex:0 0 auto;transition:transform .18s ease}
.book:hover{transform:translateY(-7px)}
.bcover{height:196px;padding:6px;background:#f8f2e6;box-shadow:0 14px 20px -12px #000a,0 2px 3px #0004,inset 0 0 0 1px rgba(30,22,14,.08)}
.bcover img{height:100%;width:auto;display:block;max-width:200px}
figcaption{display:flex;flex-direction:column;align-items:center;gap:1px;padding-top:5px;max-width:190px}
figcaption b{font-family:"Songti SC","Noto Serif CJK SC",Georgia,serif;font-size:7.8px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
figcaption span{font-size:6.4px;color:#8b8374;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
.shelf{height:14px;margin:0 -10px;background:linear-gradient(180deg,#9b704f,#6a4932 45%,#4a3020 75%,#2f1e14),repeating-linear-gradient(90deg,rgba(0,0,0,.08) 0 1px,transparent 1px 7px);box-shadow:0 1px 0 rgba(255,255,255,.32) inset,0 10px 18px -8px #0008;position:relative;z-index:1}
/* FILMS: film sleeves */
.film-binder{position:relative;padding:18px 22px 24px;background:linear-gradient(180deg,#1b1b1d,#0c0c0d);border:1px solid #2b2b2e;box-shadow:0 30px 60px -45px #000a,inset 0 0 50px #0006}
.film-head{display:flex;justify-content:space-between;font-size:8px;letter-spacing:.22em;color:#9c9486;border-bottom:1px solid #2c2c2e;padding-bottom:8px;margin-bottom:14px}
.film-row{display:flex;align-items:flex-end;justify-content:center;padding:10px 0 4px;min-height:300px}
.sleeve{position:relative;width:222px;height:326px;margin-left:-22px;background:#101011;padding:24px 10px 42px 26px;transform:rotate(var(--rot));box-shadow:0 18px 28px -14px #000c,0 2px 5px #0008;transition:transform .18s ease}
.sleeve:first-child{margin-left:0}
.sleeve:hover{transform:rotate(0) translateY(-8px)}
.perf{position:absolute;left:6px;top:8px;bottom:8px;width:12px;background-image:radial-gradient(circle,#d8d1c1 2.2px,transparent 2.6px);background-size:10px 16px;opacity:.75}
.poster{height:246px;background:#050506;overflow:hidden;box-shadow:inset 0 0 0 1px #2a2a2c;display:grid;place-items:center}
.poster img{max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;display:block;filter:saturate(.96)}
.flabel{position:absolute;left:26px;right:10px;bottom:8px;background:#f4eee1;color:#1e1a15;padding:5px 7px;display:flex;flex-direction:column;gap:1px}
.flabel b{font-family:"Songti SC",serif;font-size:8.2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.flabel span{font-size:6.2px;color:#7a7263;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sleeve::after{content:"";position:absolute;inset:0;background:linear-gradient(135deg,rgba(255,255,255,.16),transparent 30%,transparent 70%,rgba(255,255,255,.05));pointer-events:none}
/* MUSIC: cassette rack */
.cassette-rack{position:relative;padding:28px 26px 18px;background:linear-gradient(180deg,#24211c,#12100d);border:1px solid #37322a;box-shadow:0 30px 60px -45px #000a,inset 0 0 50px #0006}
.cassette-row{display:flex;justify-content:center;align-items:flex-end;gap:18px;padding:12px 0;position:relative;z-index:2}
.cassette{position:relative;width:246px;height:152px;background:linear-gradient(180deg,#3d3d40,#1b1b1d 60%,#101012);border-radius:6px;box-shadow:0 16px 24px -12px #000c,inset 0 1px 0 rgba(255,255,255,.18);transform:rotate(var(--rot));transition:transform .18s ease}
.cassette:hover{transform:rotate(0) translateY(-6px)}
.clabel{position:absolute;left:11px;top:10px;width:92px;height:92px;background:#f4eee1;padding:4px;box-shadow:0 2px 4px #0006}
.clabel img{width:100%;height:100%;object-fit:cover;display:block}
.ctitle{position:absolute;left:114px;right:11px;top:12px;color:#f0e9da;display:flex;flex-direction:column;gap:3px;max-height:78px;overflow:hidden}
.ctitle b{font-family:"Songti SC",serif;font-size:9px;line-height:1.2;font-weight:600}
.ctitle span{font-size:6.4px;color:#b9b1a2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.reels{position:absolute;left:114px;right:11px;bottom:11px;height:42px;display:flex;justify-content:space-between;align-items:center}
.reels i{width:38px;height:38px;border-radius:50%;border:2px solid #777;background:radial-gradient(circle at 50% 50%,#0b0b0c 0 18%,#262628 19% 55%,#0d0d0f 56%);box-shadow:inset 0 0 6px #000;position:relative}
.reels i::after{content:"";position:absolute;inset:14px;border-radius:50%;border:1px solid #555;background:#19191b}
.cassette::before{content:"";position:absolute;left:50%;bottom:-2px;transform:translateX(-50%);width:52px;height:8px;background:#0b0b0c;border-radius:0 0 4px 4px}
.cassette::after{content:"";position:absolute;inset:0;border-radius:6px;background:linear-gradient(135deg,rgba(255,255,255,.14),transparent 30%,transparent 72%,rgba(255,255,255,.04));pointer-events:none}
.rack-rail{height:13px;margin:6px -26px -18px;background:linear-gradient(180deg,#8a6b3d,#5a4527 55%,#2f2414);box-shadow:0 1px 0 rgba(255,255,255,.2) inset,0 8px 16px -6px #0008}
.foot{display:flex;justify-content:space-between;border-top:1px solid var(--line);margin-top:42px;padding-top:16px;font-size:9px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted)}
.foot .mid{color:var(--celadon)}
@media(max-width:1000px){.book-row,.film-row,.cassette-row{flex-wrap:wrap}.sleeve{margin-left:0}.bcover{height:170px}}
'''
body=f'''<div class="wrap"><header class="mast"><div><h1>MOUSEION</h1><div class="kicker">A private collection of books, films &amp; records</div></div><div class="seal">三境居</div></header><nav class="index"><a href="#books">I · Books</a><a href="#films">II · Films</a><a href="#music">III · Music</a></nav>
<section id="books"><div class="head"><span class="n">I</span><h2>BOOKS</h2><span class="d">The shelf · printed matter</span></div>{bookcase()}</section>
<section id="films"><div class="head"><span class="n">II</span><h2>FILMS</h2><span class="d">The film clip · sleeves &amp; sprockets</span></div>{binder()}</section>
<section id="music"><div class="head"><span class="n">III</span><h2>MUSIC</h2><span class="d">The cassette rack · tape &amp; case</span></div>{rack()}</section>
<footer class="foot"><span>MOUSEION</span><span class="mid">A private collection · kept in three rooms</span><span>NeoDB · TMDB · Open Library · iTunes</span></footer></div>'''
page=f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Mouseion</title><style>{css}</style></head><body>{body}</body></html>'
open('out/ui.html','w',encoding='utf-8').write(page)
print('bytes',len(page),'groups',{k:len(v) for k,v in groups.items()})
