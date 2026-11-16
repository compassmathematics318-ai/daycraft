import {describe,it,expect} from 'vitest'
import type {Project,Task} from './types'
import {linkedProgress,projectInput,projectValidation} from './projectUtils'

describe('project definitions',()=>{
 it('keeps server migration provenance out of project saves',()=>{const project={...projectInput(),id:'p',name:'Vector',legacy_task_id:'task',legacy_snapshot:{duration_minutes:120}} as Project;expect(projectInput(project)).not.toHaveProperty('legacy_task_id');expect(projectInput(project)).not.toHaveProperty('legacy_snapshot');expect(projectInput(project)).not.toHaveProperty('duration_minutes')})
 it('permits optional dates and half-step rating extremes',()=>{expect(projectValidation({...projectInput(),name:'Vector',importance:1,difficulty:0})).toBe('');expect(projectValidation({...projectInput(),name:'Vector',importance:9.5,difficulty:10})).toBe('')})
 it('rejects reversed project dates without inventing task deadlines',()=>expect(projectValidation({...projectInput(),name:'Vector',start_date:'2026-12-01',end_date:'2026-11-30'})).toContain('End date'))
 it.each([0,1.5,-1,100001])('rejects invalid contributor count %s',contributors=>expect(projectValidation({...projectInput(),name:'Vector',contributors})).toContain('Contributors'))
 it.each([0,10.5,5.25,NaN])('rejects invalid importance %s',importance=>expect(projectValidation({...projectInput(),name:'Vector',importance})).toContain('Importance'))
 it.each([-0.5,10.5,5.25,NaN])('rejects invalid difficulty %s',difficulty=>expect(projectValidation({...projectInput(),name:'Vector',difficulty})).toContain('Difficulty'))
 it('rejects unsafe and credential-bearing links',()=>{for(const link of ['javascript:alert(1)','https://user:secret@example.com','https://example.com/a b'])expect(projectValidation({...projectInput(),name:'Vector',links:[link]})).toContain('links')})
 it('enforces API text and list bounds',()=>{expect(projectValidation({...projectInput(),name:'Vector',goals:'x'.repeat(10001)})).toContain('Goals');expect(projectValidation({...projectInput(),name:'Vector',affiliations:Array(31).fill('Group')})).toContain('affiliations')})
})
describe('linked task progress',()=>{
 const task=(status:Task['status'],remaining_minutes=60)=>({status,remaining_minutes} as Task)
 it('does not suggest zero progress when no tasks exist',()=>expect(linkedProgress([])).toEqual({total:0,tracked:0,completed:0,percent:null,remaining:0}))
 it('uses actual task completions and excludes skipped work',()=>expect(linkedProgress([task('completed',0),task('in_progress',30),task('skipped')])).toEqual({total:3,tracked:2,completed:1,percent:50,remaining:30}))
 it('handles a project with only skipped tasks',()=>expect(linkedProgress([task('skipped')]).percent).toBeNull())
})
