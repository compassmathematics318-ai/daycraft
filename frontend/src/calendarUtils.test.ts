import {describe,it,expect} from 'vitest'
import {calendarInputInstant,calendarOverlaps,clockMinute,eventLanes,eventSlice,sundayOf,occurrenceOnDate,placementAt,placementIssue,snapMinute,wallTime,weekLabel} from './calendarUtils'
import type {Activity,Occurrence} from './types'

const occurrence:Occurrence={id:'o',activity_id:'a',source:'manual',start:'2026-11-09T23:30:00-05:00',end:'2026-11-10T00:30:00-05:00'}
describe('weekly calendar dates and precision',()=>{
 it('preserves the second fall-back occurrence when its wall-clock input is unchanged',()=>{
  expect(calendarInputInstant('2026-11-01T01:30','America/Toronto','2026-11-01T06:30:00Z')).toBe('2026-11-01T06:30:00Z')
  expect(calendarInputInstant('2026-11-01T01:45','America/Toronto','2026-11-01T06:45:00Z')).toBe('2026-11-01T06:45:00Z')
 })
 it('converts an explicitly changed assessment input using the selected timezone',()=>{
  expect(calendarInputInstant('2026-11-01T02:30','America/Toronto','2026-11-01T06:30:00Z')).toBe('2026-11-01T07:30:00.000Z')
  expect(calendarInputInstant('2026-11-01T01:30','America/Toronto')).toBe('2026-11-01T05:30:00.000Z')
 })
 it('rejects an explicitly edited assessment time inside a spring-forward gap',()=>{
  expect(()=>calendarInputInstant('2027-03-14T02:30','America/Toronto','2027-03-14T06:30:00Z')).toThrow('does not exist')
 })
 it('groups every day of November 8–14 into the same Sunday-first week',()=>{
  for(const date of ['2026-11-08','2026-11-09','2026-11-10','2026-11-11','2026-11-12','2026-11-13','2026-11-14'])expect(sundayOf(date)).toBe('2026-11-08')
  expect(sundayOf('2026-11-15')).toBe('2026-11-15')
  expect(sundayOf('2027-01-01')).toBe('2026-12-27')
  expect(sundayOf('2027-03-14')).toBe('2027-03-14')
 })
 it('labels Sunday-first same month, cross-month and cross-year weeks accurately',()=>{
  expect(weekLabel('2026-11-08')).toBe('Nov 8–14, 2026')
  expect(weekLabel('2026-11-29')).toBe('Nov 29–Dec 5, 2026')
  expect(weekLabel('2026-12-27')).toBe('Dec 27, 2026 – Jan 2, 2027')
 })
 it('snaps mouse positions to five minutes and bounds the full day',()=>{
  expect(snapMinute(542)).toBe(540)
  expect(snapMinute(543)).toBe(545)
  expect(snapMinute(-50)).toBe(0)
  expect(snapMinute(1500)).toBe(1435)
  expect(clockMinute(545)).toBe('09:05')
 })
 it('uses selected IANA timezone instead of the browser timezone',()=>{
  expect(wallTime('2026-11-09',545,'America/Toronto')).toBe('2026-11-09T14:05:00.000Z')
  expect(wallTime('2026-11-09',545,'Asia/Tokyo')).toBe('2026-11-09T00:05:00.000Z')
 })
 it('supports end-of-day midnight without turning into nonpositive duration',()=>{
  expect(wallTime('2026-11-09',1440,'America/Toronto')).toBe('2026-11-10T05:00:00.000Z')
  const value=placementAt('a','2026-11-09',1435,60,'America/Toronto')
  expect(value.activity_id).toBe('a')
  expect(Date.parse(value.end)-Date.parse(value.start)).toBe(3600000)
 })
 it('rejects a drop into the DST spring-forward gap',()=>{
  expect(()=>placementAt('a','2027-03-14',150,60,'America/Toronto')).toThrow('does not exist')
 })
 it('produces the same persisted fields for manual and drag placement',()=>{
  expect(placementAt('a','2026-11-09',543,60,'America/Toronto')).toEqual({activity_id:'a',start:wallTime('2026-11-09',545,'America/Toronto'),end:wallTime('2026-11-09',605,'America/Toronto')})
 })
})
describe('dated occurrence rendering',()=>{
 it('warns about legacy overlaps without treating adjacent meetings as collisions',()=>{
  const a={...occurrence,id:'a',start:'2026-11-09T09:00:00-05:00',end:'2026-11-09T10:00:00-05:00'},b={...a,id:'b',start:'2026-11-09T09:30:00-05:00',end:'2026-11-09T10:30:00-05:00'},c={...a,id:'c',start:'2026-11-09T10:30:00-05:00',end:'2026-11-09T11:00:00-05:00'}
  expect(calendarOverlaps([c,b,a]).map(pair=>pair.map(x=>x.id))).toEqual([['a','b']])
 })
 it('keeps overlapping imported events independently visible in separate lanes',()=>{
  const a={...occurrence,id:'a',start:'2026-11-09T09:00:00-05:00',end:'2026-11-09T10:00:00-05:00'},b={...a,id:'b',start:'2026-11-09T09:30:00-05:00',end:'2026-11-09T10:30:00-05:00'},c={...a,id:'c',start:'2026-11-09T10:30:00-05:00',end:'2026-11-09T11:00:00-05:00'}
  const lanes=eventLanes([a,b,c]);expect(lanes.get('a')).toEqual({lane:0,columns:2});expect(lanes.get('b')).toEqual({lane:1,columns:2});expect(lanes.get('c')).toEqual({lane:0,columns:1})
 })
 it('includes cross-midnight events on both occupied dates only',()=>{
  expect(occurrenceOnDate(occurrence,'2026-11-09','America/Toronto')).toBe(true)
  expect(occurrenceOnDate(occurrence,'2026-11-10','America/Toronto')).toBe(true)
  expect(occurrenceOnDate(occurrence,'2026-11-11','America/Toronto')).toBe(false)
 })
 it('clips visual portions at midnight while preserving the original event',()=>{
  expect(eventSlice(occurrence,'2026-11-09','America/Toronto')).toEqual({top:1410,height:30})
  expect(eventSlice(occurrence,'2026-11-10','America/Toronto')).toEqual({top:0,height:30})
  expect(occurrence.start).toBe('2026-11-09T23:30:00-05:00')
 })
 it('does not show midnight endings on the following date',()=>{
  expect(occurrenceOnDate({...occurrence,end:'2026-11-10T00:00:00-05:00'},'2026-11-10','America/Toronto')).toBe(false)
 })
})

describe('drag placement feedback',()=>{
 const activity:Activity={id:'a',title:'MATH147',category:'class',subtype:'Lecture',description:'',location_id:null,building:'',room:'',course:null,start_date:'2026-11-08',end_date:'2026-11-14',assessment_start:null,assessment_end:null,legacy_class_id:null}
 it('permits adjacent meetings and moving an existing meeting over itself',()=>{
  const event={...occurrence,start:'2026-11-11T10:30:00-05:00',end:'2026-11-11T11:30:00-05:00'}
  expect(placementIssue(activity,placementAt('a','2026-11-11',690),[event],'America/Toronto')).toBe(null)
  expect(placementIssue(activity,event,[event],'America/Toronto',event.id)).toBe(null)
  expect(placementIssue(activity,event,[event],'America/Toronto')).toBe('Overlaps another meeting')
 })
 it('checks both local boundary dates while allowing an exact midnight ending',()=>{
  expect(placementIssue(activity,placementAt('a','2026-11-07',630),[],'America/Toronto')).toBe("Before this block's start date")
  expect(placementIssue(activity,placementAt('a','2026-11-14',1380),[],'America/Toronto')).toBe(null)
  expect(placementIssue(activity,placementAt('a','2026-11-14',1410),[],'America/Toronto')).toBe("After this block's end date")
 })
})
