import {alternativeLocationPolicy} from './locationUtils'
import type {TaskDefinition,TaskDefinitionInput,TaskWeek,TaskWeekAssignment} from './types'
import {sundayOf} from './calendarUtils'

export const taskTypes = ['academic','personal','project_work','administrative','wellness','other'] as const
export const academicSubtypes = ['studying','assignment','assessment_preparation','reading','other'] as const
export const taskTypeNames:Record<TaskDefinition['task_type'],string> = {academic:'Academic',personal:'Personal',project_work:'Project work',administrative:'Administrative',wellness:'Wellness',other:'Other'}
export const academicSubtypeNames:Record<NonNullable<TaskDefinition['academic_subtype']>,string> = {studying:'Studying',assignment:'Assignment',assessment_preparation:'Assessment preparation',reading:'Reading',other:'Other'}
export function taskDefinitionInput(task?:TaskDefinition,projectId?:string):TaskDefinitionInput {
 if(task)return {recurrence:task.recurrence??null,title:task.title,task_type:task.task_type,session_minutes:task.session_minutes,min_sessions_per_week:task.min_sessions_per_week,min_sessions_per_day:task.min_sessions_per_day??1,max_sessions_per_day:task.max_sessions_per_day??null,importance:task.importance,difficulty:task.difficulty,description:task.description,project_id:task.project_id,academic_subtype:task.academic_subtype,due_at:task.due_at,assessment_at:task.assessment_at,deadline_at:task.deadline_at,hard_deadline:task.hard_deadline,related_activity_id:task.related_activity_id,course:task.course,earliest_start:task.earliest_start,allow_splitting:task.allow_splitting,min_chunk_minutes:task.min_chunk_minutes,dependencies:[...task.dependencies],preferred_days:[...task.preferred_days],preferred_time_of_day:task.preferred_time_of_day,preferred_start:task.preferred_start,preferred_end:task.preferred_end,location_id:task.location_id,location_requirements:[...task.location_requirements??[]],...alternativeLocationPolicy(task),room:task.room??'',location_mode:task.location_mode??(task.location_id?'required':'unspecified'),status:task.status}
 return {recurrence:null,title:'',task_type:projectId?'project_work':'academic',session_minutes:60,min_sessions_per_week:1,min_sessions_per_day:1,max_sessions_per_day:null,importance:5,difficulty:5,description:'',project_id:projectId??null,academic_subtype:projectId?null:'studying',due_at:null,assessment_at:null,deadline_at:null,hard_deadline:true,related_activity_id:null,course:'',earliest_start:null,allow_splitting:false,min_chunk_minutes:5,dependencies:[],preferred_days:[],preferred_time_of_day:'any',preferred_start:null,preferred_end:null,location_id:null,location_mode:'unspecified',location_requirements:[],allow_alternative_locations:false,alternative_location_ids:[],status:'active'}
}
export function taskValidation(task:TaskDefinitionInput,minSessions=task.min_sessions_per_week):string {
 if(task.recurrence&&[task.due_at,task.assessment_at,task.deadline_at,task.earliest_start].some(Boolean))return 'Every-week defaults cannot have absolute dates. Add a dated exception in Week Specific.'
 if(!task.title.trim())return 'Enter a task name.'
 if(task.title.trim().length>200)return 'Task name must be at most 200 characters.'
 if(!Number.isSafeInteger(task.session_minutes)||task.session_minutes<1)return 'Session length must be a positive whole number of minutes.'
 if(!Number.isSafeInteger(minSessions)||minSessions<0)return 'Minimum sessions must be a nonnegative whole number.'
 const dailyError=dailySessionValidation(task.min_sessions_per_day,task.max_sessions_per_day)
 if(dailyError)return dailyError
 if(!Number.isFinite(task.importance)||task.importance<1||task.importance>10||task.importance*2%1)return 'Importance must be 1–10 in steps of 0.5.'
 if(!Number.isFinite(task.difficulty)||task.difficulty<0||task.difficulty>10||task.difficulty*2%1)return 'Difficulty must be 0–10 in steps of 0.5.'
 if(!Number.isSafeInteger(task.min_chunk_minutes)||task.min_chunk_minutes<1)return 'Minimum chunk length must be a positive whole number of minutes.'
 if(task.allow_splitting&&task.min_chunk_minutes>task.session_minutes)return 'Minimum chunk length cannot exceed the session length.'
 if(task.preferred_start&&task.preferred_end&&task.preferred_start>=task.preferred_end)return 'Preferred start must precede preferred end.'
 if(task.task_type==='academic'&&!task.academic_subtype)return 'Choose an academic subtype.'
 return ''
}
export function assignmentProgress(assignment:TaskWeekAssignment):number|null {
 const allocated=assignment.allocated_sessions??assignment.completed_sessions+assignment.scheduled_sessions
 return assignment.min_sessions_per_week>0?Math.min(100,Math.max(0,Math.round(allocated/assignment.min_sessions_per_week*100))):null
}
export function taskDate(task:TaskDefinition):string|null {
 return task.task_type==='academic'?task.due_at??task.assessment_at:task.deadline_at
}
export function dashboardTaskContext(week:TaskWeek|null,planningDate:string) {
 const loaded=week?.week_start===sundayOf(planningDate)
 const tasks=loaded?week.assignments.flatMap(assignment=>{
  const base=week.definitions.find(item=>item.id===assignment.task_definition_id)
  const definition=assignment.effective_definition??(base?{...base,...assignment.overrides}:undefined)
  if(assignment.removed_from_week||!definition||definition.status==='completed'||(definition.status!=='active'&&!assignment.allow_inactive)||assignment.week_start!==week.week_start||['paused','completed','skipped'].includes(assignment.status))return []
  return [{definition,assignment,title:definition.title,remaining_minutes:assignment.remaining_minutes,priority:Math.min(5,Math.max(1,Math.round(definition.importance/2)))}]
 }):[]
 const dates=tasks.flatMap(task=>{
  const definition=task.definition,values=definition.task_type==='academic'?[{label:'Due',at:definition.due_at},{label:'Assessment',at:definition.assessment_at}]:[{label:'Deadline',at:definition.deadline_at}]
  return values.flatMap(value=>value.at?[{...task,id:`${task.assignment.id}:${value.label}`,label:value.label,at:value.at}]:[])
 }).sort((a,b)=>Date.parse(a.at)-Date.parse(b.at))
 return {loaded,tasks,dates,remaining_minutes:tasks.reduce((sum,task)=>sum+task.remaining_minutes,0)}
}

export function dailySessionValidation(minimum:number,maximum:number|null):string {
 if(!Number.isSafeInteger(minimum)||minimum<0)return 'Minimum work blocks on a scheduled day must be a nonnegative whole number.'
 if(maximum!==null&&(!Number.isSafeInteger(maximum)||maximum<1))return 'Maximum work blocks on a scheduled day must be a positive whole number, or empty for unlimited.'
 if(maximum!==null&&maximum<minimum)return 'Maximum work blocks on a scheduled day cannot be below the minimum.'
 return ''
}
export function recurrenceEligibleForWeek(definition:TaskDefinition,weekStart:string):boolean {
 const recurrence=definition.recurrence
 if(!recurrence)return false
 const week=sundayOf(weekStart),start=recurrence.start_week
 if(week<start||(recurrence.end_week&&week>recurrence.end_week)||(recurrence.stopped_from_week&&week>=recurrence.stopped_from_week))return false
 const difference=Math.round((Date.parse(`${week}T00:00:00Z`)-Date.parse(`${start}T00:00:00Z`))/(7*24*60*60*1000))
 return difference>=0&&difference%(recurrence.interval_weeks??1)===0
}
export function taskAssignableToWeek(definition:TaskDefinition,weekStart:string):boolean {
 return definition.status==='active'&&!recurrenceEligibleForWeek(definition,weekStart)
}
export function weekSpecificAssignments(assignments:TaskWeekAssignment[],definitions:TaskDefinition[]) {
 const byId=new Map(definitions.map(d=>[d.id,d]))
 return assignments.filter(assignment=>{
  if(assignment.removed_from_week||assignment.source==='recurring')return false
  if(assignment.source==='explicit'||assignment.source==='copy')return true
  const definition=byId.get(assignment.task_definition_id)
  return !definition?.recurrence||(!!assignment.week_start&&!recurrenceEligibleForWeek(definition,assignment.week_start))
 })
}
