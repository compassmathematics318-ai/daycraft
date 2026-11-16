import {describe,expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {BlockEditor,Planner} from './Planner'
import WorkloadLevelPicker,{workloadLevels} from './WorkloadLevel'
import {canCompleteSession,isSessionCompleted,isTaskWorkBlock} from './completionUtils'
import type {Block,Schedule,WorkloadLevel,TaskDefinition,TaskWeek} from './types'
import TasksView from './Tasks'
import {taskDefinitionInput} from './taskUtils'
import {defaultSettings} from './types'
vi.mock('./LocationPicker',()=>({default:()=>null,locationMode:()=> 'unspecified',locationModes:{unspecified:'Unspecified'}}))
const past:Block={id:'chunk',title:'Read course notes',kind:'task',start:'2020-11-12T14:00:00-05:00',end:'2020-11-12T14:30:00-05:00',task_id:null,task_definition_id:'task',task_assignment_id:'week',logical_session_id:'logical',class_id:null,location_id:null,locked:false,status:'todo',rationale:'',estimated:false}
const editor=(block:Block,onCompletion:(completed:boolean)=>void=()=>{})=>renderToStaticMarkup(<BlockEditor block={block} timezone="America/Toronto" locations={[]} busy={false} onCancel={()=>{}} onSave={()=>{}} onCompletion={onCompletion}/>)
describe('scheduled session completion',()=>{
 it('permits elapsed task work including locked and retained history, and legacy work',()=>{
  expect(canCompleteSession(past)).toBe(true)
  expect(canCompleteSession({...past,locked:true,task_assignment_id:null})).toBe(true)
  expect(canCompleteSession({...past,task_definition_id:null,task_id:'legacy'})).toBe(true)
  expect(canCompleteSession(past,Date.parse(past.end))).toBe(true)
 })
 it('rejects future or malformed end times and non-task blocks',()=>{
  expect(canCompleteSession(past,Date.parse(past.end)-1)).toBe(false)
  expect(canCompleteSession({...past,end:'invalid'})).toBe(false)
  for(const kind of ['class','personal','meal','break','travel'] as const)expect(isTaskWorkBlock({...past,kind})).toBe(false)
  expect(isTaskWorkBlock({...past,task_definition_id:null})).toBe(false)
 })
 it('uses a dedicated button and excludes generic completion for uncompleted task work',()=>{
  const html=editor(past)
  expect(html).toContain('Mark Session Completed')
  expect(html).not.toContain('<option value="completed">')
  expect(html).toContain('task completion stays separate')
  expect(html).not.toMatch(/<button[^>]*disabled[^>]*>[^<]*Mark Session Completed/)
 })
 it('disables future completion and explains when it becomes available',()=>{
  const html=editor({...past,end:'2099-01-01T14:00:00Z'})
  expect(html).toMatch(/<button type="button" class="button secondary" disabled=""/)
  expect(html).toContain('Completion is available after this work block ends.')
 })
 it('allows undo for confirmed and historical completed work without fabricating a timestamp',()=>{
  const historic={...past,status:'completed' as const}
  expect(isSessionCompleted(historic)).toBe(true)
  expect(editor(historic)).toContain('Undo Completion')
  expect(editor({...historic,completion_verified:true,completion_confirmed_at:'2020-11-12T20:00:00Z'})).toContain('Undo Completion')
  expect(historic).not.toHaveProperty('completion_confirmed_at')
  const mistakenFuture=editor({...historic,end:'2099-01-01T14:00:00Z'})
  expect(mistakenFuture).toContain('Undo Completion')
  expect(mistakenFuture).not.toMatch(/<button type="button" class="button secondary" disabled=""/)
 })
 it('does not offer completion for classes and displays verified work in the timeline',()=>{
  expect(editor({...past,kind:'class'})).not.toContain('Mark Session Completed')
  const schedule={id:'plan',date:'2020-11-12',mode:'deep',status:'feasible',solver_status:'OPTIMAL',blocks:[{...past,status:'completed'}],unallocated:[],conflicts:[],explanations:[],stats:{}} as Schedule
  const html=renderToStaticMarkup(<Planner schedule={schedule} date={schedule.date} settings={defaultSettings} workloadLevel="medium" setWorkloadLevel={()=>{}} workloadBusy={false} generating={false} generate={()=>{}} location={()=>'Home'} onEdit={()=>{}} onMove={()=>{}}/>)
  expect(html).toContain('session-verified')
  expect(html).toContain('Session completed')
  expect(html).toContain('Deep work plan')
  expect(html).not.toContain('Scheduling mode')
  expect(html.indexOf('Read course notes')).toBeLessThan(html.indexOf('Save to Schedule Archive'))
  expect(html.indexOf('Save to Schedule Archive')).toBeLessThan(html.indexOf('timeline-end'))
  expect(html.match(/Save to Schedule Archive/g)).toHaveLength(1)
 })
})
describe('workload level control',()=>{
 it('shows the five exact labels with Medium selected, linked label and active planning guidance',()=>{
  const html=renderToStaticMarkup(<WorkloadLevelPicker value="medium" onChange={()=>{}}/>)
  expect(Object.values(workloadLevels)).toEqual(['Very Low','Low','Medium','High','Very High'])
  expect(html).toContain('Workload Level</label>')
  expect(html).toContain('<option value="medium" selected="">Medium</option>')
  expect(html).toContain('aria-describedby=')
  expect(html).toContain('Reoptimize to apply changes.')
  expect(html).not.toContain('coming soon')
  expect(html).not.toContain('<option value="balanced">')
 })
 it('round trips every saved workload selection through the shared controlled picker',()=>{
  for(const value of Object.keys(workloadLevels) as WorkloadLevel[]){
   const html=renderToStaticMarkup(<WorkloadLevelPicker value={value} onChange={()=>{}}/>)
   expect(html).toContain(`<option value="${value}" selected="">${workloadLevels[value]}</option>`)
  }
 })
})

describe('verified progress apart from allocation and task status',()=>{
 it('shows partial completed minutes without counting a completed logical session or completing the task',()=>{
  const definition={...taskDefinitionInput(),id:'task',title:'Open course work',legacy_task_id:null,scheduling_model:'weekly'} as TaskDefinition
  const metrics={target_minutes:120,completed_minutes:30,verified_completed_minutes:30,completed_sessions:0,scheduled_sessions:1,planned_minutes:90,remaining_minutes:0,allocated_sessions:2,target_met:true}
  const week={week_start:'2020-11-08',week_end:'2020-11-14',definitions:[definition],assignments:[{...metrics,id:'week',task_definition_id:'task',week_start:'2020-11-08',session_minutes:60,min_sessions_per_week:2,status:'in_progress',notes:'',source:'explicit'}],sessions:[],summary:metrics} as TaskWeek
  const html=renderToStaticMarkup(<TasksView definitions={[definition]} activities={[]} projects={[]} week={week} weekStart={week.week_start} onWeekChange={()=>{}} timezone="America/Toronto" setEditor={()=>{}} busy={false} refresh={async()=>{}} taskMode="week" onTaskModeChange={()=>{}} projectFilter="" setProjectFilter={()=>{}} openProject={()=>{}}/>)
  expect(html).toContain('Verified completed work: 30m')
  expect(html).toContain('0 logical sessions verified')
  expect(html).toContain('2 of 2 minimum sessions allocated')
  expect(html).toContain('Target met')
  expect(html).toContain('Mark task completed')
  expect(html).not.toContain('Log session')
 })
})
