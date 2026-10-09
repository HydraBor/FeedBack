const hasText = value => typeof value === 'string' && Boolean(value.trim());

export function importRequirements({student, startDate, endDate, config, platform = 'acgo'}) {
  const missing = [];
  if (!student?.id) missing.push('学生档案');
  if (!startDate) missing.push('学习开始日期');
  if (!endDate) missing.push('学习结束日期');
  if (startDate && endDate && endDate < startDate) missing.push('学习日期（结束日期不能早于开始日期）');
  if (platform !== 'zhou-oj') {
    if (!hasText(config.user_id)) missing.push('学生 ACGO ID');
    if (!hasText(config.team)) missing.push('团队 ID 或链接');
  }
  if (!hasText(config.task)) missing.push(platform === 'zhou-oj' ? '周老师 OJ 比赛号或链接' : config.kind === 'contest' ? '比赛 ID 或链接' : '作业 ID 或链接');
  return missing;
}

export function studyPeriodText(startDate, endDate) {
  return startDate || endDate ? `${startDate || '待填写开始日期'} — ${endDate || '待填写结束日期'}` : '未填写';
}
