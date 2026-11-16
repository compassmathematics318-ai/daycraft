import {describe,expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import TasksView,{TaskAssociation} from './Tasks'
import {taskDefinitionInput} from './taskUtils'
import type {TaskAssociationSummary,TaskDefinition,TaskWeek,TaskWeekAssignment} from './types'
vi.mock('./LocationPicker',()=>({default:()=>null}))
const definition={...taskDefinitionInput(),id:'task',legacy_task_id:null,scheduling_model:'weekly'} as TaskDefinition
const summary:TaskAssociationSummary={assigned_week_starts:[],stored_assignment_count:0,history_week_starts:[],recurring:false,repeating_from_week:null,repeating_through_week:null,stopped_from_week:null}
const html=(value:Partial<TaskAssociationSummary>)=>renderToStaticMarkup(<TaskAssociation definition={{...definition,association_summary:{...summary,...value}}}/>)
describe('task library scheduling associations',()=>{
 it('distinguishes repeating, unassigned, and a single Sunday–Saturday date range',()=>{
  expect(html({recurring:true})).toContain('Every Week')
  expect(html({})).toContain('Unassigned')
  expect(html({assigned_week_starts:['2032-03-07']})).toContain('Mar 7–13, 2032')
 })
 it('expands all assigned weeks independent of the selected week and excludes history-only dates',()=>{
  const result=html({assigned_week_starts:['2032-03-14','2032-03-07'],history_week_starts:['2032-02-29']})
  expect(result).toContain('<details>')
  expect(result).toContain('Multiple weeks')
  expect(result).toContain('Mar 7–13, 2032')
  expect(result).toContain('Mar 14–20, 2032')
  expect(result).not.toContain('Feb 29')
 })
 it('shows a recurrence cutoff without claiming the task still repeats',()=>{
  const result=html({recurring:false,stopped_from_week:'2032-03-07'})
  expect(result).toContain('Repeating stops')
  expect(result).not.toContain('Every Week')
 })
})


describe('stopped task management cards',()=>{
 const stopped={...definition,title:'Retained weekly practice',recurrence:{kind:'weekly',start_week:'2032-03-07',end_week:null,interval_weeks:1,stopped_from_week:'2032-03-21'},association_summary:{...summary,stopped_from_week:'2032-03-21'}} as TaskDefinition
 const render=(mode:'week'|'library',assignment?:TaskWeekAssignment)=>renderToStaticMarkup(<TasksView definitions={[stopped]} activities={[]} projects={[]} week={{week_start:'2032-03-28',week_end:'2032-04-03',definitions:[stopped],assignments:assignment?[assignment]:[],sessions:[],summary:{target_minutes:60,completed_minutes:0,completed_sessions:0,scheduled_sessions:0,planned_minutes:0,remaining_minutes:60}} as TaskWeek} weekStart="2032-03-28" onWeekChange={()=>{}} timezone="America/Toronto" setEditor={()=>{}} busy={false} refresh={async()=>{}} taskMode={mode} onTaskModeChange={()=>{}} projectFilter="" setProjectFilter={()=>{}} openProject={()=>{}}/>)
 it('offers a library assignment after the cutoff and displays the explicit weekly card',()=>{
  const library=render('library').match(/<article class="panel intelligent-task-card"[\s\S]*?<\/article>/)?.[0]??''
  expect(library).toContain('Retained weekly practice')
  expect(library).toContain('Assign to week')
  const weekly=render('week',{id:'post-stop',task_definition_id:stopped.id,week_start:'2032-03-28',source:'explicit',session_minutes:60,min_sessions_per_week:1,status:'todo',notes:'',target_minutes:60,completed_minutes:0,completed_sessions:0,scheduled_sessions:0,planned_minutes:0,remaining_minutes:60}).match(/<article class="panel intelligent-task-card"[\s\S]*?<\/article>/)?.[0]??''
  expect(weekly).toContain('Retained weekly practice')
  expect(weekly).toContain('Week specific')
  expect(weekly).toContain('Adjust this week')
  expect(weekly).not.toContain('Every week')
  expect(stopped.recurrence?.stopped_from_week).toBe('2032-03-21')
 })
})
