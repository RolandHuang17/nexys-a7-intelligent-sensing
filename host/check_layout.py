from audit import ROOT,Run

run=Run('report_layout_check')
report=ROOT/'report'
main=(report/'Experiment-template.tex').read_text(encoding='utf8')
preamble=main.split('\\input{cover}')[0]
draft=preamble+r'''
\input{cover}
\title{基于 Nexys A7 的\\声振双通道瞬态事件记录仪}
\begin{document}\maketitle\frontmatter\input{frontmatter}\clearpage\tableofcontents
\mainmatter\raggedbottom\baselineskip=22pt\input{design}\input{references}\end{document}
'''
(report/'layout_check.tex').write_text(draft,encoding='utf8')
run.snapshot('报告正文布局检查：只编译设计部分，不填造未采实测章')
rc,text=run.command([r'C:/texlive/2026/bin/windows/latexmk.exe','-xelatex','-interaction=nonstopmode','-halt-on-error',
                     '-file-line-error','layout_check.tex'],'指定模板设计正文XeLaTeX布局检查',cwd=report,timeout=180)
run.manifest();print('RUN_ID='+run.run_id);raise SystemExit(rc)
