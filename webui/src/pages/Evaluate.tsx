import { useState } from 'react'
import { useKBs, useEvaluate } from '@/api/hooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { LineChart, Loader2, CheckCircle, XCircle } from 'lucide-react'

export function EvaluatePage() {
  const { data: kbs } = useKBs()
  const evaluateMutation = useEvaluate()

  const [selectedKB, setSelectedKB] = useState<string>('')
  const [questions, setQuestions] = useState<string[]>([''])
  const [groundTruths, setGroundTruths] = useState<string[]>([''])
  const [results, setResults] = useState<any>(null)

  const addQA = () => {
    setQuestions([...questions, ''])
    setGroundTruths([...groundTruths, ''])
  }

  const updateQuestion = (index: number, value: string) => {
    const newQuestions = [...questions]
    newQuestions[index] = value
    setQuestions(newQuestions)
  }

  const updateGroundTruth = (index: number, value: string) => {
    const newGroundTruths = [...groundTruths]
    newGroundTruths[index] = value
    setGroundTruths(newGroundTruths)
  }

  const handleEvaluate = async () => {
    if (!selectedKB) return
    const validQuestions = questions.filter((q) => q.trim())
    const validGroundTruths = groundTruths.filter((g) => g.trim())
    if (validQuestions.length === 0) return

    try {
      const result = await evaluateMutation.mutateAsync({
        kbId: selectedKB,
        req: {
          questions: validQuestions,
          ground_truths: validGroundTruths.length === validQuestions.length
            ? validGroundTruths
            : validQuestions.map(() => ''),
          top_k: 5,
        },
      })
      setResults(result)
    } catch (error) {
      console.error('Evaluation failed:', error)
    }
  }

  const metrics = [
    { key: 'faithfulness', label: 'Faithfulness', description: 'Answer accuracy vs context' },
    { key: 'answer_relevancy', label: 'Answer Relevancy', description: 'Answer relevance to question' },
    { key: 'context_precision', label: 'Context Precision', description: 'Retrieval quality' },
    { key: 'context_recall', label: 'Context Recall', description: 'Context coverage' },
  ]

  return (
    <div className="p-6">
      <h1 className="mb-6 text-2xl font-bold">RAG Evaluation</h1>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Configuration</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Knowledge Base</Label>
                <Select value={selectedKB} onValueChange={setSelectedKB}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a knowledge base..." />
                  </SelectTrigger>
                  <SelectContent>
                    {kbs?.map((kb) => (
                      <SelectItem key={kb.id} value={kb.id}>
                        {kb.name || kb.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Questions & Ground Truths</CardTitle>
                <Button variant="outline" size="sm" onClick={addQA}>
                  Add Q&A
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {questions.map((question, index) => (
                <div key={index} className="space-y-2">
                  <Label>Question {index + 1}</Label>
                  <Textarea
                    placeholder="Enter question..."
                    value={question}
                    onChange={(e) => updateQuestion(index, e.target.value)}
                  />
                  <Label>Ground Truth {index + 1}</Label>
                  <Textarea
                    placeholder="Enter expected answer..."
                    value={groundTruths[index]}
                    onChange={(e) => updateGroundTruth(index, e.target.value)}
                  />
                </div>
              ))}
              <Button
                onClick={handleEvaluate}
                disabled={!selectedKB || questions.every((q) => !q.trim()) || evaluateMutation.isPending}
              >
                {evaluateMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {evaluateMutation.isPending ? 'Evaluating...' : 'Run Evaluation'}
              </Button>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <LineChart className="h-5 w-5" />
                Results
              </CardTitle>
            </CardHeader>
            <CardContent>
              {results ? (
                <div className="space-y-4">
                  {metrics.map((metric) => {
                    const value = results[metric.key]
                    const isGood = value >= 0.8
                    const isBad = value < 0.5
                    return (
                      <div key={metric.key} className="space-y-2">
                        <div className="flex items-center justify-between">
                          <div>
                            <span className="font-medium">{metric.label}</span>
                            <p className="text-xs text-muted-foreground">
                              {metric.description}
                            </p>
                          </div>
                          <div className="flex items-center gap-2">
                            {isGood && <CheckCircle className="h-4 w-4 text-green-500" />}
                            {isBad && <XCircle className="h-4 w-4 text-red-500" />}
                            <Badge
                              variant={isGood ? 'default' : isBad ? 'destructive' : 'secondary'}
                            >
                              {typeof value === 'number' ? (value * 100).toFixed(1) : 'N/A'}%
                            </Badge>
                          </div>
                        </div>
                        <div className="h-2 w-full rounded-full bg-secondary">
                          <div
                            className={`h-2 rounded-full transition-all ${
                              isGood ? 'bg-green-500' : isBad ? 'bg-red-500' : 'bg-yellow-500'
                            }`}
                            style={{ width: `${Math.min((value || 0) * 100, 100)}%` }}
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className="text-center text-muted-foreground py-8">
                  Run evaluation to see results
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Metrics Guide</CardTitle>
            </CardHeader>
            <CardContent className="text-sm space-y-2 text-muted-foreground">
              <p><strong>Faithfulness:</strong> Measures how accurately the answer reflects the retrieved context. Low scores indicate hallucinations.</p>
              <p><strong>Answer Relevancy:</strong> Measures how relevant the answer is to the question. Low scores indicate irrelevant answers.</p>
              <p><strong>Context Precision:</strong> Measures how precisely the retrieved context matches the question. Low scores indicate poor retrieval.</p>
              <p><strong>Context Recall:</strong> Measures how much of the relevant context was retrieved. Low scores indicate missing information.</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

export function Evaluate() {
  return <EvaluatePage />
}