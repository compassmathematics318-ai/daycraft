import {describe,it,expect} from 'vitest'
import type {TaskDefinition,TaskWeek,TaskWeekAssignment} from './types'
import {recurrenceEligibleForWeek,taskAssignableToWeek,weekSpecificAssignments,assignmentProgress,dashboardTaskContext,taskDefinitionInput,taskValidation,dailySessionValidation} from './taskUtils'
import {sundayOf} from './calendarUtils'

describe('reusable task definitions',()=>{
 it.each([1,7,37,180,1440,1000000])('accepts exact positive session length %i without an arbitrary cap',session_minutes=>expect(taskValidation({...taskDefinitionInput(),title:'Focused work',session_minutes})).toBe(''))
 it.each([0,-1,1.5,NaN,Infinity,Number.MAX_SAFE_INTEGER+1])('rejects invalid session length %s',session_minutes=>expect(taskValidation({...taskDefinitionInput(),title:'Focused work',session_minutes})).toContain('Session length'))
 it('allows a zero weekly target',()=>expect(taskValidation({...taskDefinitionInput(),title:'Optional work',min_sessions_per_week:0})).toBe(''))
 it('preserves recurring identity metadata when editing defaults',()=>{const recurrence={kind:'weekly' as const,start_week:'2026-11-08',end_week:null,interval_weeks:1 as const};const task={...taskDefinitionInput(),id:'recurring',title:'Practice',recurrence,legacy_task_id:null,scheduling_model:'weekly'} as TaskDefinition;expect(taskDefinitionInput(task).recurrence).toEqual(recurrence)})
 it('rejects absolute dates on recurring defaults',()=>{const task={...taskDefinitionInput(),title:'Practice',recurrence:{kind:'weekly' as const,start_week:'2026-11-08',end_week:null,interval_weeks:1 as const}};expect(taskValidation(task)).toBe('');for(const key of ['due_at','assessment_at','deadline_at','earliest_start'])expect(taskValidation({...task,[key]:'2026-11-12T12:00:00-05:00'})).toContain('Every-week defaults')})
 it('keeps one-minute unsplittable sessions valid despite a larger default chunk',()=>expect(taskValidation({...taskDefinitionInput(),title:'Breathe',session_minutes:1,min_chunk_minutes:5,allow_splitting:false})).toBe(''))
 it('rejects a minimum chunk longer than a split session',()=>expect(taskValidation({...taskDefinitionInput(),title:'Study',session_minutes:7,min_chunk_minutes:8,allow_splitting:true})).toContain('cannot exceed'))
 it('rejects non-half-step importance and difficulty',()=>{expect(taskValidation({...taskDefinitionInput(),title:'Study',importance:5.25})).toContain('Importance');expect(taskValidation({...taskDefinitionInput(),title:'Study',difficulty:5.25})).toContain('Difficulty')})
 it('preserves independent academic instants and advanced preferences while stripping provenance',()=>{const task={...taskDefinitionInput(),id:'task',title:'Study',due_at:'2026-11-01T01:30:00-05:00',assessment_at:'2026-11-02T10:00:00-05:00',preferred_days:[0,2],preferred_time_of_day:'morning',hard_deadline:false,legacy_task_id:'old',scheduling_model:'legacy'} as TaskDefinition;const input=taskDefinitionInput(task);expect(input.due_at).toBe(task.due_at);expect(input.assessment_at).toBe(task.assessment_at);expect(input.preferred_days).toEqual([0,2]);expect(input.preferred_time_of_day).toBe('morning');expect(input.hard_deadline).toBe(false);expect(input).not.toHaveProperty('scheduling_model');expect(input).not.toHaveProperty('legacy_task_id')})
 it('normalizes arbitrary dates to Sunday, including year boundaries',()=>{expect(sundayOf('2026-11-11')).toBe('2026-11-08');expect(sundayOf('2027-01-01')).toBe('2026-12-27')})
})
describe('weekly scheduling target allocation',()=>{
 it('omits a percentage for zero minimum demand',()=>expect(assignmentProgress({min_sessions_per_week:0,completed_sessions:0,scheduled_sessions:0} as TaskWeekAssignment)).toBeNull())
 it('counts reserved and verified logical sessions toward the minimum',()=>expect(assignmentProgress({min_sessions_per_week:4,completed_sessions:1,scheduled_sessions:2} as TaskWeekAssignment)).toBe(75))
 it('uses canonical allocation so split and partially verified sessions are not counted twice',()=>expect(assignmentProgress({min_sessions_per_week:4,allocated_sessions:2,completed_sessions:1,scheduled_sessions:2} as TaskWeekAssignment)).toBe(50))
 it('caps display at target met while preserving allocation above the minimum',()=>{const assignment={min_sessions_per_week:2,allocated_sessions:3,status:'todo'} as TaskWeekAssignment;expect(assignmentProgress(assignment)).toBe(100);expect(assignment.allocated_sessions).toBe(3);expect(assignment.status).toBe('todo')})
})
describe('dashboard planning-week context',()=>{
 const definition={...taskDefinitionInput(),id:'future-task',title:'Future assignment',session_minutes:37,due_at:'2032-03-10T23:00:00-05:00',assessment_at:'2032-03-11T09:00:00-05:00',legacy_task_id:null,scheduling_model:'weekly'} as TaskDefinition
 const assignment={id:'future-week',task_definition_id:definition.id,week_start:'2032-03-07',session_minutes:37,min_sessions_per_week:3,status:'in_progress',notes:'',target_minutes:111,completed_minutes:37,completed_sessions:1,scheduled_sessions:0,planned_minutes:0,remaining_minutes:74} as TaskWeekAssignment
 const week:TaskWeek={week_start:'2032-03-07',week_end:'2032-03-13',definitions:[definition,{...definition,id:'unassigned',title:'Unassigned definition'}],assignments:[assignment],sessions:[],summary:{target_minutes:111,completed_minutes:37,completed_sessions:1,scheduled_sessions:0,planned_minutes:0,remaining_minutes:74}}
 it('uses selected-week remaining work without adding unassigned definitions',()=>{const context=dashboardTaskContext(week,'2032-03-10');expect(context.loaded).toBe(true);expect(context.tasks.map(task=>task.title)).toEqual(['Future assignment']);expect(context.remaining_minutes).toBe(74)})
 it('never substitutes a current or previously loaded week for a future planning date',()=>{const context=dashboardTaskContext({...week,week_start:'2026-11-08'},'2032-03-10');expect(context.loaded).toBe(false);expect(context.tasks).toEqual([]);expect(context.remaining_minutes).toBe(0)})
 it('keeps open tasks and deadlines visible after their minimum target is allocated or verified',()=>{const context=dashboardTaskContext({...week,assignments:[{...assignment,remaining_minutes:0,target_met:true,allocated_sessions:3}]},'2032-03-10');expect(context.tasks).toHaveLength(1);expect(context.dates).toHaveLength(2);expect(context.tasks[0].assignment.status).toBe('in_progress')})
 it('excludes explicitly completed definitions even with an old inactive override',()=>expect(dashboardTaskContext({...week,definitions:[{...definition,status:'completed'}],assignments:[{...assignment,allow_inactive:true}]},'2032-03-10').tasks).toEqual([]))
 it('keeps independent due and assessment dates with canonical edit context',()=>{const context=dashboardTaskContext(week,'2032-03-10');expect(context.dates.map(date=>[date.label,date.at])).toEqual([['Due',definition.due_at],['Assessment',definition.assessment_at]]);expect(context.dates[0].assignment.id).toBe('future-week');expect(context.dates[0].definition.id).toBe('future-task')})
 it('uses effective week dates and metadata instead of reusable defaults',()=>{const effective_definition={...definition,title:'This week only',due_at:'2032-03-12T20:00:00-05:00'};const context=dashboardTaskContext({...week,assignments:[{...assignment,effective_definition}]},'2032-03-10');expect(context.tasks[0].title).toBe('This week only');expect(context.dates.find(d=>d.label==='Due')?.at).toBe(effective_definition.due_at);expect(definition.title).toBe('Future assignment')})
 it('omits a skipped recurring week and respects an explicit inactive override',()=>{expect(dashboardTaskContext({...week,assignments:[{...assignment,status:'skipped'}]},'2032-03-10').tasks).toEqual([]);expect(dashboardTaskContext({...week,definitions:[{...definition,status:'paused'}],assignments:[{...assignment,allow_inactive:true}]},'2032-03-10').tasks).toHaveLength(1)})
 it('does not show explicitly completed or paused work as active',()=>{for(const change of [{status:'completed'},{status:'paused'}])expect(dashboardTaskContext({...week,assignments:[{...assignment,...change} as TaskWeekAssignment]},'2032-03-10').tasks).toEqual([]);expect(dashboardTaskContext({...week,definitions:[{...definition,status:'archived'}]},'2032-03-10').tasks).toEqual([])})
})


describe('daily task session bounds',()=>{
 it('defaults to one daily session and unlimited maximum',()=>{expect(taskDefinitionInput().min_sessions_per_day).toBe(1);expect(taskDefinitionInput().max_sessions_per_day).toBeNull()})
 it.each([0,1,3,1000000,Number.MAX_SAFE_INTEGER])('accepts nonnegative safe minimum %s without an arbitrary cap',minimum=>expect(dailySessionValidation(minimum,null)).toBe(''))
 it.each([-1,0.5,NaN,Infinity,Number.MAX_SAFE_INTEGER+1])('rejects invalid daily minimum %s',minimum=>expect(dailySessionValidation(minimum,null)).toContain('Minimum work blocks on a scheduled day'))
 it.each([0,-1,0.5,NaN,Infinity,Number.MAX_SAFE_INTEGER+1])('rejects invalid daily maximum %s',maximum=>expect(dailySessionValidation(0,maximum)).toContain('Maximum work blocks on a scheduled day'))
 it('requires a maximum at least the minimum and preserves explicit zero minimum',()=>{expect(dailySessionValidation(3,2)).toContain('below the minimum');expect(dailySessionValidation(3,3)).toBe('');expect(dailySessionValidation(0,1)).toBe('');const input={...taskDefinitionInput(),title:'Work',min_sessions_per_day:3,max_sessions_per_day:2};expect(taskValidation(input)).toContain('below the minimum')})
 it('round trips daily defaults and task-specific room without changing the source',()=>{const original={...taskDefinitionInput(),id:'t',legacy_task_id:null,scheduling_model:'weekly' as const,min_sessions_per_day:0,max_sessions_per_day:5,room:'2201'};const input=taskDefinitionInput(original);expect(input.min_sessions_per_day).toBe(0);expect(input.max_sessions_per_day).toBe(5);expect(input.room).toBe('2201')})
})

 describe('management tab separation',()=>{it('excludes inherited and materialized recurring work while retaining explicit and copied assignments',()=>{const definitions=[{id:'rhythm',recurrence:{kind:'weekly'}},{id:'ordinary'}] as TaskDefinition[];const assignments=[{id:'virtual',task_definition_id:'rhythm',source:'recurring',is_virtual:true},{id:'override',task_definition_id:'rhythm',source:'recurring',is_virtual:false},{id:'legacy',task_definition_id:'rhythm'},{id:'explicit',task_definition_id:'ordinary',source:'explicit'},{id:'copy',task_definition_id:'copy',source:'copy'}] as TaskWeekAssignment[];expect(weekSpecificAssignments(assignments,definitions).map(a=>a.id)).toEqual(['explicit','copy']);expect(assignments).toHaveLength(5)})})

describe('task venue permission round trips',()=>{
 it('starts new tasks with alternative locations disabled',()=>expect(taskDefinitionInput()).toMatchObject({allow_alternative_locations:false,alternative_location_ids:[]}))
 it('preserves explicit alternative venues while editing unrelated task metadata',()=>{
  const task={...taskDefinitionInput(),id:'gym',legacy_task_id:null,scheduling_model:'weekly' as const,location_id:'pac',location_mode:'preferred' as const,allow_alternative_locations:true,alternative_location_ids:['field']}
  const input=taskDefinitionInput(task)
  expect(input).toMatchObject({location_id:'pac',location_mode:'preferred',allow_alternative_locations:true,alternative_location_ids:['field']})
  input.alternative_location_ids!.push('another')
  expect(task.alternative_location_ids).toEqual(['field'])
 })
})

it('preserves complete explicit venue needs when editing a task definition',()=>{
 const task={...taskDefinitionInput(),id:'gym',legacy_task_id:null,scheduling_model:'weekly' as const,location_requirements:['fitness_training','weights']}
 expect(taskDefinitionInput(task).location_requirements).toEqual(['fitness_training','weights'])
})

describe('task relationship and explicit completion preservation',()=>{
 it('keeps an existing course and stable activity ID without changing task type',()=>{const original={...taskDefinitionInput(),id:'t',task_type:'wellness' as const,course:'Legacy course',related_activity_id:'commitment-id',legacy_task_id:null,scheduling_model:'weekly' as const};expect(taskDefinitionInput(original)).toMatchObject({course:'Legacy course',related_activity_id:'commitment-id',task_type:'wellness'})})
 it('round trips an explicitly completed task without creating session completion',()=>{const original={...taskDefinitionInput(),id:'t',status:'completed' as const,legacy_task_id:null,scheduling_model:'weekly' as const};expect(taskDefinitionInput(original).status).toBe('completed');expect(original.min_sessions_per_week).toBe(1)})
})


describe('reusing a task outside its repeating weeks',()=>{
 const stopped={...taskDefinitionInput(),id:'stopped',title:'Retained weekly practice',status:'active',recurrence:{kind:'weekly',start_week:'2032-03-07',end_week:null,interval_weeks:1,stopped_from_week:'2032-03-21'},legacy_task_id:null,scheduling_model:'weekly'} as TaskDefinition
 it('uses inclusive start/end, exclusive stop, and the interval from the original start',()=>{
  expect(recurrenceEligibleForWeek(stopped,'2032-02-29')).toBe(false)
  expect(recurrenceEligibleForWeek(stopped,'2032-03-07')).toBe(true)
  expect(recurrenceEligibleForWeek(stopped,'2032-03-14')).toBe(true)
  expect(recurrenceEligibleForWeek(stopped,'2032-03-21')).toBe(false)
  expect(recurrenceEligibleForWeek(stopped,'2032-03-28')).toBe(false)
  const bounded={...stopped,recurrence:{...stopped.recurrence!,end_week:'2032-03-14',stopped_from_week:null}}
  expect(recurrenceEligibleForWeek(bounded,'2032-03-14')).toBe(true)
  expect(recurrenceEligibleForWeek(bounded,'2032-03-21')).toBe(false)
  const interval={...stopped,recurrence:{...stopped.recurrence!,interval_weeks:2,stopped_from_week:null}} as unknown as TaskDefinition
  expect(recurrenceEligibleForWeek(interval,'2032-03-14')).toBe(false)
  expect(recurrenceEligibleForWeek(interval,'2032-03-21')).toBe(true)
 })
 it('offers stopped work for a post-cutoff week without erasing recurrence metadata',()=>{
  const snapshot=JSON.stringify(stopped)
  expect(taskAssignableToWeek(stopped,'2032-03-14')).toBe(false)
  expect(taskAssignableToWeek(stopped,'2032-03-21')).toBe(true)
  expect(taskAssignableToWeek({...stopped,status:'paused'},'2032-03-21')).toBe(false)
  expect(JSON.stringify(stopped)).toBe(snapshot)
  expect(taskDefinitionInput(stopped).recurrence).toEqual(stopped.recurrence)
 })
 it('shows actual explicit and copied post-cutoff work while keeping recurring history separate',()=>{
  const assignments=[{id:'inherited',task_definition_id:stopped.id,week_start:'2032-03-14',source:'recurring'},{id:'history',task_definition_id:stopped.id,week_start:'2032-03-28',source:'recurring'},{id:'reuse',task_definition_id:stopped.id,week_start:'2032-03-28',source:'explicit'},{id:'copied',task_definition_id:stopped.id,week_start:'2032-04-04',source:'copy'},{id:'removed',task_definition_id:stopped.id,week_start:'2032-04-11',source:'explicit',removed_from_week:true},{id:'legacy-before',task_definition_id:stopped.id,week_start:'2032-03-14'},{id:'legacy-after',task_definition_id:stopped.id,week_start:'2032-03-28'}] as TaskWeekAssignment[]
  expect(weekSpecificAssignments(assignments,[stopped]).map(a=>a.id)).toEqual(['reuse','copied','legacy-after'])
 })
})
