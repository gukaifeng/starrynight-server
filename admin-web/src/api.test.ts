import {describe,it,expect} from 'vitest'
import {keysOf,editableValues,compact,type Resource} from './api'
const resource:Resource={id:'users',name:'用户',group:'账户',description:'',keys:['id'],fields:['id','profile','version'],edit:['profile'],actions:[]}
describe('management payload boundaries',()=>{
  it('sends only the primary key and editable fields',()=>{
    const row={id:'u',version:3,profile:{display_name:'星'},password_hash:'must not submit'}
    expect(keysOf(resource,row)).toEqual({id:'u'})
    expect(editableValues(resource,row)).toEqual({profile:{display_name:'星'}})
  })
  it('keeps empty and false states distinct',()=>{expect(compact(false)).toBe('否');expect(compact(null)).toBe('—');expect(compact({display_name:'星夜'})).toBe('星夜')})
})
