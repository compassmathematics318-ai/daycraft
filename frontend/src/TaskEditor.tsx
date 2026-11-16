import {useId,useState} from 'react'

import type {FormEvent} from 'react'

import {BookOpen,CalendarDays,ChevronDown,Save} from 'lucide-react'

import type {Activity,Place,Project,TaskDefinition,TaskDefinitionInput,TaskWeekAssignment,TaskWeekInput} from './types'

import {Field} from './Forms'
import LocationPicker from './LocationPicker'
import RelatedActivityPicker from './RelatedActivityPicker'

import {calendarInputInstant,sundayOf,weekLabel} from './calendarUtils'

import {errorMessage,localDate,localInput} from './utils'

import {academicSubtypeNames,academicSubtypes,taskDefinitionInput,taskTypeNames,taskTypes,taskValidation} from './taskUtils'

import './tasks.css'



export interface TaskSave {definition:TaskDefinitionInput;assignment:Omit<TaskWeekInput,'task_definition_id'>|null}

function TaskRating({name,value,min,onChange,hint}:{name:string;value:number;min:number;onChange:(value:number)=>void;hint:string}) {

 const id=useId()

 return <div className="project-rating"><div className="rating-heading"><label htmlFor={id}>{name}</label><output htmlFor={id}>{value.toFixed(1)}<small>/ 10</small></output></div><input id={id} type="range" min={min} max={10} step={0.5} value={value} onChange={e=>onChange(Number(e.target.value))} aria-describedby={`${id}-hint`} aria-valuetext={`${value} out of 10`}/><div className="rating-scale"><span>{min} · {name==='Importance'?'Least important':'Negligible'}</span><span>10 · {name==='Importance'?'Extremely important':'Extremely challenging'}</span></div><p id={`${id}-hint`}>{hint} Arrow keys adjust by 0.5.</p></div>

}

export default function TaskEditor({task,projectId,weekStart,assignment,assignByDefault=true,recurring=false,projects,activities,locations,definitions,timezone,onSave,onCancel,busy}:{task?:TaskDefinition;projectId?:string;weekStart:string;assignment?:TaskWeekAssignment;assignByDefault?:boolean;recurring?:boolean;projects:Project[];activities:Activity[];locations:Place[];definitions:TaskDefinition[];timezone:string;onSave:(value:TaskSave)=>void;onCancel:()=>void;busy:boolean}) {

 const [value,setValue]=useState(()=>taskDefinitionInput(task,projectId)),[target,setTarget]=useState(assignment?.min_sessions_per_week??task?.min_sessions_per_week??1),[week]=useState(assignment?.week_start??weekStart),[assign]=useState(!!assignment||(!task&&assignByDefault)),[weekStatus,setWeekStatus]=useState(assignment?.status??'todo'),[error,setError]=useState('')

 const [dates,setDates]=useState(()=>({due_at:task?.due_at?localInput(task.due_at,timezone):'',assessment_at:task?.assessment_at?localInput(task.assessment_at,timezone):'',deadline_at:task?.deadline_at?localInput(task.deadline_at,timezone):'',earliest_start:task?.earliest_start?localInput(task.earliest_start,timezone):''}))

 const patch=(change:Partial<TaskDefinitionInput>)=>setValue(old=>({...old,...change}))

 const setDate=(key:keyof typeof dates,next:string)=>setDates(old=>({...old,[key]:next}))

 const submit=(event:FormEvent)=>{event.preventDefault();try{const instant=(key:keyof typeof dates)=>dates[key]?calendarInputInstant(dates[key],timezone,task?.[key]):null;const next={...value,title:value.title.trim(),min_sessions_per_week:target,recurrence:recurring?(task?.recurrence??{kind:'weekly' as const,start_week:sundayOf(localDate(new Date(),timezone)),end_week:null,interval_weeks:1 as const}):null,due_at:!recurring&&value.task_type==='academic'?instant('due_at'):null,assessment_at:!recurring&&value.task_type==='academic'?instant('assessment_at'):null,deadline_at:recurring||value.task_type==='academic'?null:instant('deadline_at'),earliest_start:recurring?null:instant('earliest_start'),academic_subtype:value.task_type==='academic'?value.academic_subtype:null,related_activity_id:value.related_activity_id,course:value.course};const message=taskValidation(next,target);setError(message);if(!message)onSave({definition:next,assignment:!recurring&&assign?{week_start:sundayOf(week),session_minutes:value.session_minutes,min_sessions_per_week:target,status:weekStatus,notes:assignment?.notes??''}:null})}catch(error){setError(errorMessage(error))}}

 const inactiveProject=projects.find(p=>p.id===value.project_id&&['paused','archived'].includes(p.status))

 return <form className="task-form" onSubmit={submit}>{error&&<p className="project-form-error" role="alert">{error}</p>}<p className="task-form-intro">{recurring?'Build a weekly rhythm. This task contributes a fresh target each week, with a separate scheduling target.':assign?`Work for ${weekLabel(sundayOf(week))}. The weekly assignment is kept automatically.`:'Save reusable work now; assign it to a week when you are ready.'}</p><div className="form-grid">

 <Field label="Task name"><input required autoFocus maxLength={200} value={value.title} onChange={e=>patch({title:e.target.value})} placeholder="Study calculus, implement the semantic processor…"/></Field>

 <div className="two-cols"><Field label="Task type"><select value={value.task_type} onChange={e=>{const task_type=e.target.value as TaskDefinition['task_type'];patch({task_type,academic_subtype:task_type==='academic'?(value.academic_subtype??'studying'):null})}}>{taskTypes.map(type=><option key={type} value={type}>{taskTypeNames[type]}</option>)}</select></Field><Field label="Session length (minutes)" hint="Any positive whole number. Choose the time this work actually needs."><input required type="number" min={1} step={1} value={value.session_minutes} onChange={e=>patch({session_minutes:Number(e.target.value)})}/></Field></div>

 {!recurring&&<Field label={assign?'Minimum sessions for selected week':'Default minimum sessions when assigned to a week'} hint={assign?'Soft scheduling target for the selected week. Daycraft may schedule fewer or more sessions when appropriate.':'Default soft scheduling target when this reusable task is assigned to a week.'}><input type="number" required min={0} step={1} value={target} onChange={e=>setTarget(Number(e.target.value))}/></Field>}

 {inactiveProject&&<p className="project-context-note">{inactiveProject.name} is {inactiveProject.status}. Its tasks are excluded from automatic scheduling unless explicitly included in the daily planner.</p>}

 {recurring&&<section className="task-form-section"><h3><CalendarDays size={16}/>Every week</h3><Field label="Minimum sessions each week" hint="A fresh soft target each week. Pausing stops automatic planning and keeps your history."><input type="number" required min={0} step={1} value={target} onChange={e=>setTarget(Number(e.target.value))}/></Field><p className="task-form-intro">No specific week or absolute deadline is attached. Use Adjust selected week on the recurring task for an exception.</p></section>}

 {assignment&&!recurring&&<Field label="Week status"><select value={weekStatus} onChange={e=>setWeekStatus(e.target.value as typeof weekStatus)}><option value="todo">To do</option><option value="in_progress">In progress</option><option value="completed">Completed</option><option value="paused">Paused this week</option></select></Field>}

 <section className="task-form-section"><h3>Work blocks on scheduled days</h3><div className="two-cols"><Field label="Minimum work blocks on a scheduled day" hint="Soft target when scheduled. Zero means no daily minimum."><input type="number" required min={0} step={1} value={value.min_sessions_per_day} onChange={e=>patch({min_sessions_per_day:Number(e.target.value)})}/></Field><Field label="Maximum work blocks on a scheduled day" hint="Hard limit when scheduled. Leave empty for unlimited."><input type="number" min={1} step={1} value={value.max_sessions_per_day??''} onChange={e=>patch({max_sessions_per_day:e.target.value===''?null:Number(e.target.value)})}/></Field></div><p className="task-form-intro">Unscheduled days can have zero blocks. Split chunks each count as a daily work block; weekly targets count logical sessions.</p></section>

 <div className="project-ratings"><TaskRating name="Importance" min={1} value={value.importance} onChange={importance=>patch({importance})} hint="Contributes to priority alongside dates and project importance."/><TaskRating name="Difficulty" min={0} value={value.difficulty} onChange={difficulty=>patch({difficulty})} hint="Describes the challenge. Your session length sets the work estimate."/></div>

 {value.task_type==='academic'?<section className="task-form-section"><h3><BookOpen size={16}/>Academic context</h3><div className="form-grid"><Field label="Academic subtype"><select required value={value.academic_subtype??''} onChange={e=>patch({academic_subtype:e.target.value as TaskDefinition['academic_subtype']})}><option value="" disabled>Choose academic subtype</option>{academicSubtypes.map(subtype=><option key={subtype} value={subtype}>{academicSubtypeNames[subtype]}</option>)}</select></Field>{!recurring&&<div className="two-cols"><Field label={`Due date (${timezone}, optional)`} hint="When this work is due. Independent of the assessment time."><input type="datetime-local" value={dates.due_at} onChange={e=>setDate('due_at',e.target.value)}/></Field><Field label={`Assessment date (${timezone}, optional)`} hint="When the assessment takes place. Does not create a calendar meeting."><input type="datetime-local" value={dates.assessment_at} onChange={e=>setDate('assessment_at',e.target.value)}/></Field></div>}</div></section>:!recurring&&<Field label={`Deadline (${timezone}, optional)`} hint="Leave empty for flexible work. Scheduling still respects your availability."><input type="datetime-local" value={dates.deadline_at} onChange={e=>setDate('deadline_at',e.target.value)}/></Field>}

 <RelatedActivityPicker activities={activities} projects={projects} value={value.related_activity_id} onChange={related_activity_id=>patch({related_activity_id})} projectId={value.project_id} onProjectChange={project_id=>patch({project_id})}/>

 {value.course&&<p className="project-context-note">Preserved legacy course: {value.course}</p>}

 <LocationPicker label="Work location" value={value} onChange={patch} locations={locations}/>

 <Field label="Description (optional)" hint="Purpose, context, steps, or anything that will help you return to the work."><textarea rows={4} maxLength={20000} value={value.description} onChange={e=>patch({description:e.target.value})}/></Field>

 <label className="check"><input type="checkbox" checked={value.allow_splitting} onChange={e=>patch({allow_splitting:e.target.checked})}/>Allow a session to be split into smaller chunks</label>{value.allow_splitting&&<Field label="Minimum chunk length (minutes)" hint="Chunks contribute to the same logical session; they do not count as extra sessions."><input type="number" required min={1} step={1} value={value.min_chunk_minutes} onChange={e=>patch({min_chunk_minutes:Number(e.target.value)})}/></Field>}

 <details className="task-form-more"><summary>Advanced options <ChevronDown size={16}/></summary><div className="form-grid"><Field label="Task availability" hint="Applies to this reusable task across all weeks."><select value={value.status} onChange={e=>patch({status:e.target.value as TaskDefinition['status']})}><option value="active">Active</option><option value="paused">Paused</option><option value="completed">Completed</option><option value="archived">Archived</option></select></Field>{!recurring&&<Field label={`Earliest start (${timezone}, optional)`}><input type="datetime-local" value={dates.earliest_start} onChange={e=>setDate('earliest_start',e.target.value)}/></Field>}<Field label="Preferred time of day" hint="A planning preference; availability and hard constraints still apply."><select value={value.preferred_time_of_day} onChange={e=>patch({preferred_time_of_day:e.target.value as TaskDefinition['preferred_time_of_day']})}><option value="any">Flexible · any time</option><option value="morning">Morning</option><option value="afternoon">Afternoon</option><option value="evening">Evening</option></select></Field><fieldset className="weekday-field"><legend>Preferred days (optional)</legend><div className="weekdays">{(['Sun','Mon','Tue','Wed','Thu','Fri','Sat'] as const).map((day,index)=>{const number=(index+6)%7;return <label className={value.preferred_days.includes(number)?'selected':''} key={day}><input type="checkbox" checked={value.preferred_days.includes(number)} onChange={e=>patch({preferred_days:e.target.checked?[...value.preferred_days,number]:value.preferred_days.filter(d=>d!==number)})}/>{day}</label>})}</div></fieldset><div className="two-cols"><Field label="Preferred start (optional)"><input type="time" step={300} value={value.preferred_start??''} onChange={e=>patch({preferred_start:e.target.value||null})}/></Field><Field label="Preferred end (optional)"><input type="time" step={300} value={value.preferred_end??''} onChange={e=>patch({preferred_end:e.target.value||null})}/></Field></div>{definitions.some(item=>item.id!==task?.id)&&<fieldset className="dependencies"><legend>Complete these tasks first</legend>{definitions.filter(item=>item.id!==task?.id).map(item=><label className="check" key={item.id}><input type="checkbox" checked={value.dependencies.includes(item.id)} onChange={e=>patch({dependencies:e.target.checked?[...value.dependencies,item.id]:value.dependencies.filter(id=>id!==item.id)})}/>{item.title}</label>)}</fieldset>}</div></details>

 {task?.scheduling_model==='legacy'&&<p className="project-context-note">Your original work total and completed progress have been preserved. Existing work remains finite; no extra weekly sessions are created automatically.</p>}

 {task&&<p className="project-task-context">Changes to this reusable definition apply across weeks. This week’s target and progress stay attached to its assignment.</p>}

 </div><div className="form-actions"><button type="button" className="button secondary" onClick={onCancel}>Cancel</button><button className="button primary" disabled={busy}><Save size={16}/>{busy?'Saving…':'Save task'}</button></div></form>

}

