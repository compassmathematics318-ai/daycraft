import {useEffect,useId,useRef,useState} from 'react'
import {ChevronDown,X} from 'lucide-react'
import type {Activity,Project} from './types'
import './relatedEntities.css'

export const relatedActivityLabel='Related class, assessment, commitment, or project (optional)'
export function activityRelationshipLabel(activity:Activity) {
 const category=activity.category==='class'?'Class':activity.category==='assessment'?'Assessment':'Commitment'
 return [activity.title,category,activity.subtype,activity.course,activity.building,activity.room].filter(Boolean).join(' · ')
}
export function relatedActivityOptions(activities:Activity[],query='') {
 return [{id:null as string|null,label:'No related activity',search:'No related activity'},...activities.map(activity=>({id:activity.id,label:activityRelationshipLabel(activity)+(activities.filter(item=>item.title===activity.title).length>1?` · ID ${activity.id.slice(-8)}`:''),search:activityRelationshipLabel(activity)+' '+activity.id})).sort((a,b)=>a.label.localeCompare(b.label))].filter(option=>!query||option.search.toLowerCase().includes(query.toLowerCase()))
}


export type RelatedEntity={kind:'activity'|'project';id:string}
export const relationshipGroups=['Classes','Assessments','Commitments','Personal projects'] as const
export function relatedEntityOptions(activities:Activity[],projects:Project[],query='',excludeActivityId?:string) {
 const options=[...activities.filter(a=>a.id!==excludeActivityId).map(a=>({key:`activity:${a.id}`,entity:{kind:'activity' as const,id:a.id},group:a.category==='class'?'Classes':a.category==='assessment'?'Assessments':'Commitments',label:activityRelationshipLabel(a)+(activities.filter(item=>item.title===a.title).length>1?` · ID ${a.id.slice(-8)}`:''),search:[activityRelationshipLabel(a),a.id].join(' ')})),...projects.map(p=>({key:`project:${p.id}`,entity:{kind:'project' as const,id:p.id},group:'Personal projects',label:[p.name,'Personal project',p.status,...p.affiliations,projects.filter(item=>item.name===p.name).length>1?`ID ${p.id.slice(-8)}`:''].filter(Boolean).join(' · '),search:[p.name,'personal project',p.status,...p.affiliations,p.id].join(' ')}))]
 return options.filter(o=>o.search.toLowerCase().includes(query.trim().toLowerCase())).sort((a,b)=>relationshipGroups.indexOf(a.group as typeof relationshipGroups[number])-relationshipGroups.indexOf(b.group as typeof relationshipGroups[number])||a.label.localeCompare(b.label))
}

export function NoMatchingEntitiesOption() {
 return <div role="option" aria-disabled="true" aria-selected="false">No matching entities.</div>
}

export default function RelatedEntityPicker({activities,projects=[],value,onChange,excludeActivityId,projectId,onProjectChange,singleValue,onSingleChange,projectReadOnly=false}:{activities:Activity[];projects?:Project[];value?:string|null;onChange?:(id:string|null)=>void;excludeActivityId?:string;projectId?:string|null;onProjectChange?:(id:string|null)=>void;singleValue?:RelatedEntity|null;onSingleChange?:(entity:RelatedEntity|null)=>void;projectReadOnly?:boolean}) {
 const id=useId(),input=useRef<HTMLInputElement>(null),list=useRef<HTMLDivElement>(null)
 const [open,setOpen]=useState(false),[query,setQuery]=useState(''),[active,setActive]=useState(0)
 const all=relatedEntityOptions(activities,projects,'',excludeActivityId),options=relatedEntityOptions(activities,projectReadOnly?[]:projects,query,excludeActivityId)
 const selected=onSingleChange?(singleValue?[singleValue]:[]):[...(value?[{kind:'activity' as const,id:value}]:[]),...(projectId?[{kind:'project' as const,id:projectId}]:[])]
 const labelFor=(entity:RelatedEntity)=>all.find(o=>o.key===`${entity.kind}:${entity.id}`)?.label??`Unavailable ${entity.kind} · ID ${entity.id}`
 useEffect(()=>{if(open)list.current?.scrollIntoView({block:'nearest'})},[open,query])
 useEffect(()=>{if(open)document.getElementById(`${id}-option-${active}`)?.scrollIntoView({block:'nearest'})},[open,active,id])
 const choose=(entity:RelatedEntity)=>{if(onSingleChange)onSingleChange(entity);else if(entity.kind==='project')onProjectChange?.(entity.id);else onChange?.(entity.id);setOpen(false);setQuery('');input.current?.focus()}
 const clear=(entity:RelatedEntity)=>{if(onSingleChange)onSingleChange(null);else if(entity.kind==='project')onProjectChange?.(null);else onChange?.(null)}
 return <div className="field related-activity-picker" onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget)){setOpen(false);setQuery('')}}}>
  <label htmlFor={id}>{relatedActivityLabel}</label>
  <div className="related-activity-control"><input id={id} ref={input} role="combobox" autoComplete="off" aria-autocomplete="list" aria-expanded={open} aria-controls={`${id}-options`} aria-activedescendant={open&&options[active]?`${id}-option-${active}`:undefined} aria-describedby={`${id}-hint`} value={open?query:selected.map(labelFor).join('; ')} placeholder="Search classes, assessments, commitments, projects…" onClick={()=>{setOpen(true);setActive(0)}} onChange={event=>{setQuery(event.target.value);setActive(0);setOpen(true)}} onKeyDown={event=>{if(event.key==='Escape'&&open){event.preventDefault();event.stopPropagation();setOpen(false);setQuery('')}else if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();setOpen(true);setActive(old=>options.length?(!open?(event.key==='ArrowDown'?0:options.length-1):Math.max(0,Math.min(options.length-1,old+(event.key==='ArrowDown'?1:-1)))):0)}else if(event.key==='Enter'&&open){event.preventDefault();if(options[active])choose(options[active].entity)}}}/><button type="button" aria-label={open?'Close related entities':'Show related entities'} aria-expanded={open} onClick={()=>{setOpen(!open);setQuery('');setActive(0);input.current?.focus()}}><ChevronDown size={16}/></button>
  {open&&<div ref={list} className="related-activity-options" id={`${id}-options`} role="listbox" aria-multiselectable={!onSingleChange} aria-label="Existing related entities">{relationshipGroups.map(group=>{const grouped=options.filter(o=>o.group===group);return grouped.length?<div role="group" aria-label={group} key={group}><div className="related-entity-group">{group}</div>{grouped.map(option=>{const index=options.indexOf(option);return <div id={`${id}-option-${index}`} key={option.key} title={`${option.entity.kind} ID ${option.entity.id}`} role="option" aria-selected={selected.some(s=>s.kind===option.entity.kind&&s.id===option.entity.id)} className={index===active?'active':''} onMouseDown={event=>event.preventDefault()} onMouseEnter={()=>setActive(index)} onClick={()=>choose(option.entity)}>{option.label}</div>})}</div>:null})}{!options.length&&<NoMatchingEntitiesOption/>}</div>}</div>
  {!!selected.length&&<div className="related-entity-selected">{selected.map(entity=><span key={`${entity.kind}:${entity.id}`} title={`${entity.kind} ID ${entity.id}`}><span>{labelFor(entity)}</span>{entity.kind==='project'&&projectReadOnly?<small>Task project</small>:<button type="button" aria-label={`Remove link to ${labelFor(entity)}`} onClick={()=>clear(entity)}><X size={13}/></button>}</span>)}</div>}
  <small id={`${id}-hint`}>{onSingleChange?'Choose an existing entity, or leave unlinked.':'Choose an activity or project. Each replaces its own link; other context is kept.'} Search by name, type, or ID. Arrow keys browse; Enter selects.{projectReadOnly?' Project context is inherited from the reusable task.':''}</small>
 </div>
}
