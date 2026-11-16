import {describe,expect,it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import MealList from './MealList'
import {mealDropIndex,moveMeal} from './mealOrder'
import type {Meal} from './types'

const meals:Meal[]=[
 {id:'breakfast',name:'Same name',duration_minutes:30,time:'08:35',enabled:true,location_id:'home'},
 {id:'lunch',name:'Same name',duration_minutes:45,time:null,enabled:false,location_id:null},
 {id:'dinner',name:'Evening meal',duration_minutes:30},
]

describe('meal ordering',()=>{
 it('moves in both directions and retains every original object and field, including disabled meals and stored times',()=>{
  const original=structuredClone(meals)
  const down=moveMeal(meals,0,2)
  expect(down).toEqual([original[1],original[2],original[0]])
  expect(down[2]).toBe(meals[0])
  expect(down[0]).toBe(meals[1])
  expect(down[1]).toBe(meals[2])
  expect(moveMeal(down,2,0)).toEqual(original)
  expect(meals).toEqual(original)
 })
 it('leaves invalid, boundary and no-op moves unchanged',()=>{
  for(const [from,to] of [[0,-1],[2,3],[0,0],[-1,1],[3,1],[0,NaN],[.5,1]])expect(moveMeal(meals,from,to)).toBe(meals)
  expect(moveMeal([],0,1)).toEqual([])
 })
 it('calculates insertion positions across differently sized rows and clamps outside the list',()=>{
  const centers=[75,220,430,570]
  expect(mealDropIndex(centers,74,1)).toBe(0)
  expect(mealDropIndex(centers,76,1)).toBe(1)
  expect(mealDropIndex(centers,431,0)).toBe(2)
  expect(mealDropIndex(centers,400,3)).toBe(2)
  expect(mealDropIndex(centers,-999,3)).toBe(0)
  expect(mealDropIndex(centers,9999,0)).toBe(3)
 })
 it('renders named drag controls, accessible arrows with focusable bounds, and announcements without exposing retained time',()=>{
  const html=renderToStaticMarkup(<MealList meals={meals} locations={[{id:'home',name:'Kitchen',lat:0,lon:0,notes:'',travel_overrides:{}}]} onChange={()=>{}}/>)
  expect(html).toContain('<ol class="meal-list ordered-meal-list" aria-label="Meal order">')
  expect(html).toContain('aria-label="Drag Evening meal to reorder"')
  expect(html).toContain('aria-label="Move Same name up" aria-disabled="true"')
  expect(html).toContain('aria-label="Move Evening meal down" aria-disabled="true"')
  expect(html).toContain('role="status" aria-live="polite" aria-atomic="true"')
  expect(html).toContain('Save preferences to apply it.')
  expect(html).toContain('value="45"')
  expect(html).toContain('Kitchen')
  expect(html).not.toContain('08:35')
  expect(html).not.toContain('disabled=""')
 })
 it('keeps an empty or single-meal list usable without introducing meal IDs',()=>{
  const meal:Meal={name:'Only meal',duration_minutes:30}
  const html=renderToStaticMarkup(<MealList meals={[meal]} locations={[]} onChange={()=>{}}/>)
  expect(html).toContain('aria-label="Drag Only meal to reorder" aria-describedby=')
  expect(html).toContain('aria-disabled="true"')
  expect(html).not.toContain('data-meal-id=')
  expect(meal).not.toHaveProperty('id')
  expect(renderToStaticMarkup(<MealList meals={[]} locations={[]} onChange={()=>{}}/>)).toContain('aria-label="Meal order"></ol>')
 })
})
