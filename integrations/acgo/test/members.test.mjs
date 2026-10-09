import test from 'node:test';
import assert from 'node:assert/strict';
import {memberRoster} from '../core.mjs';

test('member roster paginates, keeps exact IDs and exposes only remarks',async()=>{
  const pages=[{totalCount:3,list:[{userId:'9007199254740993',teamUserName:' 学生甲 ',groupId:7,phone:'private'},
    {userId:2,teamUserName:'学生乙',groupId:7}]},{totalCount:3,list:[{userId:3,teamUserName:'',nickname:'不能冒充真名',groupId:7}]}];
  const roster=await memberRoster({groupId:'7',loadPage:async page=>pages[page-1]});
  assert.deepEqual(roster,[{user_id:'9007199254740993',name:'学生甲'},{user_id:'2',name:'学生乙'},{user_id:'3',name:''}]);
});
test('member roster rejects repeated pages and wrong group',async()=>{
  await assert.rejects(memberRoster({groupId:'7',loadPage:async()=>({totalCount:2,list:[{userId:1,teamUserName:'甲',groupId:7}]})}),/重复/);
  await assert.rejects(memberRoster({groupId:'7',loadPage:async()=>({totalCount:1,list:[{userId:1,teamUserName:'甲',groupId:8}]})}),/分组/);
});
test('member roster rejects changing counts and incomplete pages',async()=>{
  await assert.rejects(memberRoster({groupId:'7',loadPage:async page=>({totalCount:page===1?2:3,list:[{userId:page,groupId:7}]})}),/人数变化/);
  await assert.rejects(memberRoster({groupId:'7',loadPage:async()=>({totalCount:1,list:[]})}),/分页不完整/);
});
