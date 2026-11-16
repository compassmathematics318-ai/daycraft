import {describe,expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import type {TaskDefinition} from './types'
import {taskDefinitionInput} from './taskUtils'
import TaskEditor from './TaskEditor'

vi.mock('./LocationPicker',()=>({default:()=>null}))

describe('academic subtype editing',()=>{
 it('shows an explicit unselected subtype for existing null metadata without inferring a value',()=>{
  const task={...taskDefinitionInput(),id:'old-task',academic_subtype:null,legacy_task_id:null,scheduling_model:'weekly' as const} satisfies TaskDefinition
  const html=renderToStaticMarkup(<TaskEditor task={task} weekStart="2032-03-07" projects={[]} activities={[]} locations={[]} definitions={[]} timezone="America/Toronto" busy={false} onSave={()=>{}} onCancel={()=>{}}/>)
  expect(html).toMatch(/<option value="" disabled="" selected="">Choose academic subtype<\/option>/)
  expect(html).not.toMatch(/<option value="studying" selected="">/)
  expect(task.academic_subtype).toBeNull()
  expect(taskDefinitionInput(task).academic_subtype).toBeNull()
 })
})


describe('unified task context',()=>{
 it('keeps existing project and activity identities together and sends no output-only association metadata',()=>{
  const task={...taskDefinitionInput(),id:'linked-task',project_id:'project-id',related_activity_id:'activity-id',legacy_task_id:null,scheduling_model:'weekly' as const,association_summary:{assigned_week_starts:[],stored_assignment_count:0,history_week_starts:[],recurring:false,repeating_from_week:null,repeating_through_week:null,stopped_from_week:null}} satisfies TaskDefinition
  const html=renderToStaticMarkup(<TaskEditor task={task} weekStart="2032-03-07" projects={[]} activities={[]} locations={[]} definitions={[]} timezone="America/Toronto" busy={false} onSave={()=>{}} onCancel={()=>{}}/>)
  expect(html).toContain('Related class, assessment, commitment, or project (optional)')
  expect(html).toContain('project-id')
  expect(html).toContain('activity-id')
  expect(html).not.toContain('Associated project (optional)')
  const input=taskDefinitionInput(task)
  expect(input).toMatchObject({project_id:'project-id',related_activity_id:'activity-id'})
  expect(input).not.toHaveProperty('association_summary')
 })
})
