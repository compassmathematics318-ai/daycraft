import {describe,expect,it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import ScheduleDateSelector,{scheduleDateLabel} from './ScheduleDateSelector'
import {localDate,nextDate} from './utils'

describe('shared schedule date selection',()=>{
 it('labels the active date clearly and retains accessible navigation and direct input',()=>{
  const html=renderToStaticMarkup(<ScheduleDateSelector date="2026-03-08" timezone="America/Toronto" onChange={()=>{}}/>)
  for(const text of ['Schedule Date','Sunday, March 8, 2026','Previous day','Next day','Planning date','Today','Tomorrow','value="2026-03-08"'])expect(html).toContain(text)
 })
 it('uses calendar days across DST, leap dates and year boundaries',()=>{
  expect(nextDate('2026-03-08',1)).toBe('2026-03-09')
  expect(nextDate('2026-11-01',-1)).toBe('2026-10-31')
  expect(nextDate('2028-02-28',1)).toBe('2028-02-29')
  expect(nextDate('2026-12-31',1)).toBe('2027-01-01')
  expect(scheduleDateLabel('2026-11-01')).toBe('Sunday, November 1, 2026')
 })
 it('derives Today from the configured timezone near midnight',()=>{
  const instant=new Date('2026-11-15T02:00:00Z')
  expect(localDate(instant,'America/Toronto')).toBe('2026-11-14')
  expect(localDate(instant,'Asia/Tokyo')).toBe('2026-11-15')
 })
})
