import React,{useState} from 'react';

export function SelectionActions({total,selected,onChange}){
  return <div className="inline selection-actions"><button type="button" onClick={()=>onChange(Array.from({length:total},(_,i)=>i))}>全选</button><button type="button" onClick={()=>onChange([])}>全不选</button><button type="button" onClick={()=>{const chosen=new Set(selected);onChange(Array.from({length:total},(_,i)=>i).filter(i=>!chosen.has(i)))}}>反选</button><small>已选 {selected.length} / {total} 道题</small></div>;
}

export default function QuestionCard({title,meta,actions,children,className='acgo-question',initialOpen=false}){
  const [open,setOpen]=useState(initialOpen);
  return <details className={'fold-question '+className} open={open} onToggle={e=>setOpen(e.currentTarget.open)}><summary><span className="question-title">{title}</span><span className="question-meta">{meta}</span>{actions}</summary>{open&&<div className="question-body">{children}</div>}</details>;
}

export const taskLabel=source=>(source.platform==='csp_exam'?'周老师 OJ · ':'ACGO · ')+(source.kind==='homework'?'作业 ':'比赛 ')+(source.task_title||source.task_id);
