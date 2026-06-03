import { z } from 'zod'

export const ScenarioEnum = z.enum(['feed', 'detail', 'ad', 'membership', 'social'])
export const AspectRatioEnum = z.enum(['9:16', '16:9', '1:1', '4:5'])

export const CreateTaskBody = z.object({
  sourceContentId: z.string().min(1),
  sourceContentType: z.enum(['video', 'episode']),
  sourceVideoUrl: z.string().min(1),
  title: z.string().optional(),
  description: z.string().optional(),
  category: z.string().optional(),
  tags: z.array(z.string()).default([]),
  targetScenarios: z.array(ScenarioEnum).min(1),
  targetDurations: z.array(z.number().int().positive()).min(1),
  targetAspectRatios: z.array(AspectRatioEnum).min(1).default(['9:16']),
  targetLanguages: z.array(z.string()).min(1).default(['zh-CN']),
  clipCount: z.number().int().positive().default(3),
})
export type CreateTaskInput = z.infer<typeof CreateTaskBody>

export const ReviewBody = z.object({
  status: z.enum(['approved', 'rejected']),
  title: z.string().optional(),
  coverText: z.string().optional(),
  recommendationText: z.string().optional(),
})
export type ReviewInput = z.infer<typeof ReviewBody>
