#!/usr/bin/env python3
import argparse, subprocess
from pathlib import Path

def run(cmd): return subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
ap=argparse.ArgumentParser(); ap.add_argument('--production',required=True); ap.add_argument('--worktrees',required=True); ap.add_argument('--keep',type=int,default=3)
ns=ap.parse_args(); prod=Path(ns.production); root=Path(ns.worktrees)
if not root.exists(): raise SystemExit(0)
items=sorted([p for p in root.iterdir() if p.is_dir()],key=lambda p:p.name,reverse=True); kept=0
for p in items:
    status=run(['git','-C',str(p),'status','--porcelain']).stdout.strip()
    head=run(['git','-C',str(p),'rev-parse','HEAD']).stdout.strip()
    mb=run(['git','-C',str(prod),'merge-base','HEAD',head]).stdout.strip()
    if status or head!=mb: continue
    kept+=1
    if kept<=ns.keep: continue
    run(['git','-C',str(prod),'worktree','remove','--force',str(p)])
    for b in run(['git','-C',str(prod),'branch','--format=%(refname:short)','--points-at',head]).stdout.splitlines():
        if b.startswith('self-improvement/'): run(['git','-C',str(prod),'branch','-D',b])
