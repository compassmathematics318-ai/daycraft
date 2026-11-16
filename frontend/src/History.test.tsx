import {describe,expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {ArchiveCard,ArchiveControls,ArchiveDeleteDialog,ArchiveDetail,CompletedRow} from './History'
import {groupByCompletionDay,historyTimestamp} from './historyUtils'
import type {CompletedItem,ScheduleArchive} from './historyTypes'
import type {Block,Schedule} from './types'
vi.mock('./LocationPicker',()=>({default:()=>null,locationMode:()=> 'unspecified',locationModes:{unspecified:'Unspecified'}}))

const block:Block={id:'chunk-1',title:'Original work title',kind:'task',start:'2026-11-11T23:30:00-05:00',end:'2026-11-12T00:00:00-05:00',task_id:null,task_definition_id:'task-1',task_assignment_id:'week-1',logical_session_id:'session-1',chunk_index:0,class_id:null,location_id:'place-1',locked:true,status:'completed',completion_verified:true,completion_confirmed_at:'2026-11-13T02:15:00Z',rationale:'Time reserved before the deadline.',description:'Original task description',estimated:false}
const plan:Schedule={id:'plan-1',date:'2026-11-11',mode:'balanced',status:'feasible',solver_status:'OPTIMAL',blocks:[block],unallocated:[{task_id:'other',title:'Unallocated original task',minutes:20,reason:'No space before deadline.'}],conflicts:['Original conflict'],explanations:['Original solver explanation.'],stats:{}}
const archive:ScheduleArchive={id:'archive-1',version_number:2,source_schedule_id:'plan-1',source_revision_id:'revision-1',date:plan.date,created_at:'2026-11-12T18:00:00Z',updated_at:'2026-11-13T02:15:00Z',attached:false,workload_level:null,mode:'balanced',block_count:1,completed_count:1,completed_minutes:30,total_minutes:30,payload:{...plan,blocks:[{...block,location_label:'Original library · Quiet room',project_snapshot:{name:'Original project'},activity_snapshot:{title:'Original linked course'}}]}}
const completed:CompletedItem={id:'completion-1',source_type:'scheduled_block',source_schedule_id:'plan-1',source_block_id:'chunk-1',archive_id:'archive-1',date:'2026-11-12',completion_date:'2026-11-12',confirmed_at:'2026-11-13T02:15:00Z',scheduled_date:'2026-11-11',scheduled_start:block.start,scheduled_end:block.end,related_activity_title:'Original linked course',week_start:'2026-11-08',assignment_source:'recurring',completed_minutes:30,title:'Original work title',description:'Original task description',category:'academic',task_definition_id:'task-1',task_assignment_id:'week-1',logical_session_id:'session-1',logical_target_minutes:60,logical_completed_minutes:30,logical_session_complete:false,project_title:'Original project',location_label:'Original library',block,task_snapshot:null,project_snapshot:null,location_snapshot:null}

describe('completion history semantics',()=>{
 it('offers reversal for scheduled, manual and undated records and prevents repeated clicks while updating',()=>{
  for(const source_type of ['scheduled_block','manual_session','legacy_undated'] as const){
   const html=renderToStaticMarkup(<CompletedRow item={{...completed,source_type}} timezone="America/Toronto" onOpenArchive={()=>{}} onReverse={()=>{}}/> )
   expect(html).toContain('Mark as Not Completed')
   const pending=renderToStaticMarkup(<CompletedRow item={{...completed,source_type}} timezone="America/Toronto" onOpenArchive={()=>{}} onReverse={()=>{}} reversing={completed.id}/> )
   expect(pending).toContain('Updating...')
   expect(pending).toMatch(/<button[^>]*disabled=""/)
  }
 })
 it('groups by actual confirmation date in the user timezone rather than scheduled date',()=>{
  const items=[completed,{...completed,id:'second',confirmed_at:'2026-11-13T06:00:00Z'},{...completed,id:'undated',confirmed_at:null}]
  const groups=groupByCompletionDay(items,'America/Toronto')
  expect(groups.map(group=>group.date)).toEqual(['2026-11-13','2026-11-12',null])
  expect(groups[1].items[0].scheduled_date).toBe('2026-11-11')
  expect(groupByCompletionDay([completed],'Asia/Tokyo')[0].date).toBe('2026-11-13')
 })
 it('does not fabricate timestamps for earlier completed work',()=>{
  expect(historyTimestamp(null,'America/Toronto')).toBe('Not recorded')
  const html=renderToStaticMarkup(<CompletedRow item={{...completed,source_type:'legacy_undated',confirmed_at:null,archive_id:null}} timezone="America/Toronto" onOpenArchive={()=>{}}/> )
  expect(html).toContain('Earlier completed work')
  expect(html).toContain('Completion confirmed: Not recorded')
  expect(html).not.toContain('View archived plan')
 })
 it('distinguishes completed chunks from whole logical sessions and shows associations',()=>{
  const html=renderToStaticMarkup(<CompletedRow item={completed} timezone="America/Toronto" onOpenArchive={()=>{}}/> )
  for(const text of ['Work chunk completed','30m of 1h in logical session','Original project','Original linked course','Originally scheduled: 2026-11-11','2026-11-08','recurring assignment','View archived plan'])expect(html).toContain(text)
  expect(html).not.toContain('Logical session complete')
  const whole=renderToStaticMarkup(<CompletedRow item={{...completed,logical_session_complete:true,logical_completed_minutes:60}} timezone="America/Toronto" onOpenArchive={()=>{}}/> )
  expect(whole).toContain('Logical session complete')
 })
 it('labels manually recorded sessions without inventing a scheduled time',()=>{
  const html=renderToStaticMarkup(<CompletedRow item={{...completed,source_type:'manual_session',scheduled_start:null,scheduled_end:null,scheduled_date:null,block:null,archive_id:null}} timezone="America/Toronto" onOpenArchive={()=>{}}/> )
  expect(html).toContain('Recorded session')
  expect(html).toContain('Manually recorded session')
  expect(html).not.toContain('Originally scheduled:')
  expect(html).not.toContain('Work chunk completed')
 })
 it('links to the current scheduled day and a surviving task without exposing internal identifiers',()=>{
  const html=renderToStaticMarkup(<CompletedRow item={completed} timezone="America/Toronto" onOpenArchive={()=>{}} onOpenPlan={()=>{}} onOpenTask={()=>{}}/> )
  expect(html).toContain('Open current plan for 2026-11-11')
  expect(html).toContain('Open task')
  expect(html).not.toContain('week-1')
  expect(html).not.toContain('session-1')
  expect(html).not.toContain('Work association')
 })
})

describe('saved schedule presentation',()=>{
 it('shows an explicit save for unarchived plans and autosync/version controls for attached plans',()=>{
  const unsaved=renderToStaticMarkup(<ArchiveControls schedule={plan} timezone="America/Toronto"/> )
  expect(unsaved).toContain('This plan is not archived')
  expect(unsaved).toContain('Save to Schedule Archive')
  expect(unsaved).not.toContain('Save New Version')
  const saved=renderToStaticMarkup(<ArchiveControls schedule={{...plan,archive_id:'archive-1',archive_updated_at:archive.updated_at}} timezone="America/Toronto" onOpen={()=>{}}/> )
  expect(saved).toContain('Saved to Archive · Autosync on')
  expect(saved).toContain('Save New Version')
  expect(saved).toMatch(/class="button primary archive-save-primary" disabled=""/)
  expect(saved.indexOf('archive-save-primary')).toBeLessThan(saved.indexOf('archive-version-actions'))
  expect(saved).toContain('View in Archive')
  expect(saved).toContain('Generating again preserves this version')
 })
 it('identifies the saved day and distinguishes saving stale work from regeneration',()=>{
  const html=renderToStaticMarkup(<ArchiveControls schedule={{...plan,needs_regeneration:true}} timezone="America/Toronto" disabled/> )
  expect(html).toContain('November 11, 2026')
  expect(html).toContain('Saving preserves this displayed plan. Reoptimize separately')
  expect(html).toMatch(/<button[^>]*disabled=""/)
 })
 it('describes permanent deletion with the specific date, version and save time',()=>{
  const html=renderToStaticMarkup(<ArchiveDeleteDialog archive={archive} timezone="America/Toronto" busy={false} error="" onClose={()=>{}} onConfirm={()=>{}}/> )
  expect(html).toContain('Delete this archived schedule?')
  expect(html).toContain('Are you sure you want to permanently delete this schedule from your archive? This action cannot be undone.')
  expect(html).toContain('November 11, 2026')
  expect(html).toContain('<dt>Version</dt><dd>2</dd>')
  expect(html).toContain('Saved')
  expect(html).toContain(historyTimestamp(archive.created_at,'America/Toronto'))
  expect(html).toContain('data-cancel-archive-delete')
  expect(html).toContain('Delete Permanently')
  const busy=renderToStaticMarkup(<ArchiveDeleteDialog archive={archive} timezone="America/Toronto" busy error="Keep this error visible" onClose={()=>{}} onConfirm={()=>{}}/> )
  expect(busy).toMatch(/data-cancel-archive-delete="true" class="button secondary" disabled=""/)
  expect(busy).toContain('role="alert">Keep this error visible')
 })
 it('preserves unknown workload instead of inferring a current setting',()=>{
  const html=renderToStaticMarkup(<ArchiveCard archive={archive} timezone="America/Toronto" onOpen={()=>{}} onDelete={()=>{}}/> )
  expect(html).toContain('Workload: Not recorded')
  expect(html).toContain('Preserved version')
  expect(html).toContain('Version 2')
  expect(html).toContain('Scheduled work')
  expect(html).toContain('Delete from Archive</button>')
  expect(html).toContain('aria-label="Delete from Archive: 2026-11-11 version 2 saved')
  expect(html).not.toContain('Medium')
 })
 it('renders the complete read-only historical timeline, context, conflicts, unmet work and explanation',()=>{
  const kinds=['class','travel','meal','break','personal','project'] as const
  const full={...archive,payload:{...archive.payload,blocks:[...archive.payload.blocks,...kinds.map((kind,i)=>({...block,id:`other-${i}`,kind,title:`Original ${kind}`,completion_confirmed_at:null,status:'todo' as const}))]}}
  const html=renderToStaticMarkup(<ArchiveDetail archive={full} timezone="America/Toronto"/> )
  for(const kind of kinds)expect(html).toContain(`Original ${kind}`)
  for(const text of ['Original work title','Original task description','Original library','Original project','Original linked course','Original conflict','Unallocated original task','No space before deadline.','Original solver explanation.','Locked','Task completion is tracked separately.'])expect(html).toContain(text)
  expect(html).toContain('Complete timeline · 7 activities')
  expect(html).toContain('Work chunk \u00b7 Part of a logical session')
  expect(html).not.toContain('Chunk 1')
  expect(html).not.toContain('draggable')
  expect(html).not.toContain('<input')
  expect(html).not.toContain('Save &amp; validate')
 })
})
