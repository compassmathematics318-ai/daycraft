import {describe,it,expect,vi,afterEach} from 'vitest'
import {localIso,localInput,localDate,nextDate,classOnDate,duration,api,minutesBetween} from './utils'
import type {ClassItem} from './types'
afterEach(()=>vi.unstubAllGlobals())
describe('timezone-safe scheduling inputs',()=>{
 it('interprets Toronto winter time independently from browser timezone',()=>expect(localIso('2026-11-09T09:00','America/Toronto')).toBe('2026-11-09T14:00:00.000Z'))
 it('interprets positive-offset timezones',()=>expect(localIso('2026-11-09T09:00','Asia/Tokyo')).toBe('2026-11-09T00:00:00.000Z'))
 it('preserves summer daylight saving offsets',()=>expect(localIso('2026-06-09T09:00','America/Toronto')).toBe('2026-06-09T13:00:00.000Z'))
 it('rejects nonexistent spring-forward wall times',()=>expect(()=>localIso('2026-03-08T02:30','America/Toronto')).toThrow('does not exist'))
 it('chooses the first occurrence of fall-back repeated time',()=>expect(localIso('2026-11-01T01:30','America/Toronto')).toBe('2026-11-01T05:30:00.000Z'))
 it('rejects invalid calendar dates instead of rolling forward',()=>expect(()=>localIso('2026-02-30T09:00','America/Toronto')).toThrow('valid'))
 it('round-trips midnight without hour24 artifacts',()=>expect(localInput(localIso('2026-11-09T00:00','America/Toronto'),'America/Toronto')).toBe('2026-11-09T00:00'))
 it('uses selected timezone for day boundary',()=>expect(localDate(new Date('2026-11-09T02:00:00Z'),'America/Toronto')).toBe('2026-11-08'))
 it('advances dates across years',()=>expect(nextDate('2026-12-31',1)).toBe('2027-01-01'))
 it('measures DST transitions by elapsed time',()=>expect(minutesBetween('2026-03-08T01:30:00-05:00','2026-03-08T03:30:00-04:00')).toBe(60))
})
describe('recurring commitments',()=>{
 const item:ClassItem={id:'c',title:'Calculus',class_type:'Lecture',date:null,weekdays:[0,2],start_time:'09:00',end_time:'10:00',start_date:'2026-11-09',end_date:'2026-12-01',exceptions:['2026-11-11'],location_id:null,building:'',room:''}
 it('matches a recurring Monday',()=>expect(classOnDate(item,'2026-11-09')).toBe(true))
 it('respects exception dates',()=>expect(classOnDate(item,'2026-11-11')).toBe(false))
 it('respects inclusive recurrence bounds',()=>{expect(classOnDate(item,'2026-11-02')).toBe(false);expect(classOnDate(item,'2026-12-02')).toBe(false)})
 it('uses a specific date instead of weekdays',()=>expect(classOnDate({...item,date:'2026-11-10'},'2026-11-10')).toBe(true))
})
describe('API feedback',()=>{
 it('surfaces field-validation failures to the user',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,json:async()=>({detail:[{loc:['body','title'],msg:'Field required'}]})}));await expect(api('/tasks','POST',{})).rejects.toThrow('title: Field required')})
 it('supports successful deletion with an empty response',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,status:204}));await expect(api('/tasks/id','DELETE')).resolves.toBeUndefined()})
 it('formats practical durations',()=>{expect(duration(125)).toBe('2h 5m');expect(duration(30)).toBe('30m')})
})

it('available time merges overlapping commitments and clips working boundaries',async()=>{
 const {availableMinutes}=await import('./utils')
 expect(availableMinutes('2026-11-09T08:00:00Z','2026-11-09T12:00:00Z',[
  {start:'2026-11-09T07:00:00Z',end:'2026-11-09T09:00:00Z'},
  {start:'2026-11-09T08:30:00Z',end:'2026-11-09T10:00:00Z'},
  {start:'2026-11-09T11:30:00Z',end:'2026-11-09T13:00:00Z'}
 ])).toBe(90)
})

it('orders mixed UTC and local-offset activities by instant without mutating data',async()=>{
 const {chronological}=await import('./utils')
 const input=[{start:'2026-11-09T09:00:00-05:00'},{start:'2026-11-09T13:00:00Z'}]
 expect(chronological(input)[0].start).toBe('2026-11-09T13:00:00Z')
 expect(input[0].start).toBe('2026-11-09T09:00:00-05:00')
})
