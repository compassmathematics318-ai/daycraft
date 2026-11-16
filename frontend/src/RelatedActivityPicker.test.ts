import {describe,expect,it} from 'vitest'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import type {Activity,Project} from './types'
import {NoMatchingEntitiesOption,relatedActivityOptions,relatedEntityOptions} from './RelatedActivityPicker'

const activities=[
 {id:'class-lecture-12345678',title:'Calculus',category:'class',subtype:'Lecture',course:'MATH 137',building:'MC',room:'101'},
 {id:'class-lab-87654321',title:'Calculus',category:'class',subtype:'Lab',course:'MATH 137'},
 {id:'exam-12345678',title:'Calculus midterm',category:'assessment',subtype:null},
 {id:'personal-12345678',title:'Training',category:'commitment',subtype:'Personal'},
 {id:'group-12345678',title:'Study group',category:'commitment',subtype:'Groupwork'},
] as Activity[]

describe('task relationships use existing activity identities',()=>{
 it('includes classes, assessments, personal commitments and groupwork without calendar placement',()=>{
  expect(relatedActivityOptions(activities).map(option=>option.id).sort()).toEqual([null,...activities.map(activity=>activity.id)].sort())
  expect(relatedActivityOptions([])).toHaveLength(1)
 })
 it('distinguishes duplicate names by subtype and stable ID while preserving IDs',()=>{
  const options=relatedActivityOptions(activities,'Calculus')
  expect(options.find(option=>option.id===activities[0].id)?.label).toContain('Class · Lecture · MATH 137 · MC · 101 · ID 12345678')
  expect(options.find(option=>option.id===activities[1].id)?.label).toContain('Class · Lab · MATH 137 · ID 87654321')
 })
 it('searches category, subtype, retained course, venue and complete ID',()=>{
  for(const query of ['commitment','Groupwork','MATH 137','MC','class-lecture-12345678'])expect(relatedActivityOptions(activities,query).length).toBeGreaterThan(0)
  expect(relatedActivityOptions(activities,'exam-12345678').map(option=>option.id)).toEqual(['exam-12345678'])
 })
 it('never creates a relationship from an ambiguous typed name',()=>{
  const snapshot=JSON.stringify(activities)
  expect(relatedActivityOptions(activities,'Calculus')).toHaveLength(3)
  expect(relatedActivityOptions(activities,'unlisted activity')).toEqual([])
  expect(JSON.stringify(activities)).toBe(snapshot)
 })
})


describe('shared grouped entity choices',()=>{
 const projects=[{id:activities[0].id,name:'Calculus',status:'active',affiliations:['Math club']},{id:'second-project',name:'Calculus',status:'planning',affiliations:[]}] as Project[]
 it('groups all entity types and namespaces overlapping stable IDs',()=>{
  const options=relatedEntityOptions(activities,projects)
  expect([...new Set(options.map(o=>o.group))]).toEqual(['Classes','Assessments','Commitments','Personal projects'])
  expect(options.filter(o=>o.entity.id===activities[0].id).map(o=>o.key)).toEqual([`activity:${activities[0].id}`,`project:${activities[0].id}`])
  expect(options.find(o=>o.key==='project:second-project')?.label).toContain('ID -project')
 })
 it('searches projects by affiliation and identity and excludes only the edited activity',()=>{
  expect(relatedEntityOptions(activities,projects,'Math club').map(o=>o.key)).toEqual([`project:${activities[0].id}`])
  expect(relatedEntityOptions(activities,projects,'',activities[0].id).some(o=>o.key===`activity:${activities[0].id}`)).toBe(false)
  expect(relatedEntityOptions(activities,projects,'',activities[0].id).some(o=>o.key===`project:${activities[0].id}`)).toBe(true)
 })
})


describe('empty related entity searches',()=>{
 it('keeps a disabled option in the listbox and has no selectable or fabricated entity',()=>{
  const results=relatedEntityOptions(activities,[],'no-existing-entity-has-this-name')
  expect(results).toEqual([])
  const html=renderToStaticMarkup(createElement('div',{role:'listbox'},createElement(NoMatchingEntitiesOption)))
  expect(html).toContain('<div role="option" aria-disabled="true" aria-selected="false">No matching entities.</div>')
  expect(html).not.toContain('aria-selected="true"')
  expect(html).not.toContain('tabindex')
 })
})
