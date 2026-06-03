import { describe, it, expect } from 'vitest'
import { CreateTaskBody, ReviewBody } from '../src/schemas.js'

describe('schemas', () => {
  it('accepts a valid create-task body and applies defaults', () => {
    const parsed = CreateTaskBody.parse({
      sourceContentId: '12345',
      sourceContentType: 'episode',
      sourceVideoUrl: 'file:///tmp/x.mp4',
      targetScenarios: ['feed'],
      targetDurations: [15, 30],
    })
    expect(parsed.targetAspectRatios).toEqual(['9:16'])
    expect(parsed.targetLanguages).toEqual(['zh-CN'])
    expect(parsed.clipCount).toBe(3)
    expect(parsed.tags).toEqual([])
  })

  it('rejects empty sourceContentId (isolated)', () => {
    const r = CreateTaskBody.safeParse({
      sourceContentId: '',
      sourceContentType: 'episode',
      sourceVideoUrl: 'file:///tmp/x.mp4',
      targetScenarios: ['feed'],
      targetDurations: [15],
    })
    expect(r.success).toBe(false)
  })

  it('rejects an invalid review status', () => {
    expect(ReviewBody.safeParse({ status: 'pending' }).success).toBe(false)
  })

  it('parses a review body', () => {
    expect(ReviewBody.parse({ status: 'approved', title: 'x' }).status).toBe('approved')
  })
})
