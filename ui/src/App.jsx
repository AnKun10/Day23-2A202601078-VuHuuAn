import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  App as AntApp,
  Alert,
  Badge,
  Button,
  Card,
  ConfigProvider,
  Drawer,
  Empty,
  Flex,
  Input,
  Layout,
  Modal,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  theme,
} from 'antd'
import {
  ApartmentOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  PartitionOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
} from '@ant-design/icons'
import { createRun, decide, getExamples, getGraph, getRuns } from './api'

const { Header, Content } = Layout
const { Title, Text, Paragraph } = Typography

const ROUTE_COLORS = {
  simple: 'blue',
  tool: 'geekblue',
  missing_info: 'gold',
  risky: 'red',
  error: 'volcano',
}
const STATUS_META = {
  completed: { status: 'success', text: 'Completed' },
  awaiting_approval: { status: 'warning', text: 'Awaiting approval' },
  running: { status: 'processing', text: 'Running' },
}

function RouteTag({ route }) {
  if (!route) return <Tag>—</Tag>
  return <Tag color={ROUTE_COLORS[route] || 'default'}>{route}</Tag>
}

function StatusBadge({ status }) {
  const meta = STATUS_META[status] || { status: 'default', text: status }
  return <Badge status={meta.status} text={meta.text} />
}

function GraphDrawer({ open, onClose }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    let cancelled = false
    ;(async () => {
      try {
        const { mermaid: code } = await getGraph()
        const mermaid = (await import('mermaid')).default
        mermaid.initialize({ startOnLoad: false, theme: 'neutral' })
        const { svg } = await mermaid.render('graphDiagram', code)
        if (!cancelled && ref.current) ref.current.innerHTML = svg
      } catch (e) {
        if (ref.current) ref.current.textContent = 'Failed to render diagram: ' + e.message
      }
    })()
    return () => {
      cancelled = true
    }
  }, [open])
  return (
    <Drawer title="Compiled graph" width={640} open={open} onClose={onClose}>
      <Paragraph type="secondary">
        The live LangGraph topology (solid = fixed edge, dotted = conditional). Risky tickets
        stop at <Text code>approval</Text> and wait for a human decision.
      </Paragraph>
      <div ref={ref} style={{ overflowX: 'auto' }} />
    </Drawer>
  )
}

function Console() {
  const { message } = AntApp.useApp()
  const [runs, setRuns] = useState([])
  const [examples, setExamples] = useState([])
  const [query, setQuery] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [graphOpen, setGraphOpen] = useState(false)
  const [review, setReview] = useState(null) // run awaiting approval, shown in modal
  const [deciding, setDeciding] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setRuns(await getRuns())
    } catch (e) {
      message.error(e.message)
    }
  }, [message])

  useEffect(() => {
    getExamples().then(setExamples).catch(() => {})
    refresh()
    const t = setInterval(refresh, 4000)
    return () => clearInterval(t)
  }, [refresh])

  const submit = async () => {
    const q = query.trim()
    if (!q) return message.warning('Enter a support ticket first')
    setSubmitting(true)
    try {
      const run = await createRun(q)
      setQuery('')
      await refresh()
      if (run.status === 'awaiting_approval') {
        message.warning('Risky action — human approval required')
        setReview(run)
      } else {
        message.success(`Routed as "${run.route}" and completed`)
      }
    } catch (e) {
      message.error(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  const submitDecision = async (approved) => {
    if (!review) return
    setDeciding(true)
    try {
      const updated = await decide(review.thread_id, {
        approved,
        reviewer: 'console-user',
        comment: approved ? 'Approved from console' : 'Rejected from console',
      })
      message[approved ? 'success' : 'info'](
        approved ? 'Approved — action executed' : 'Rejected — routed to clarification',
      )
      setReview(null)
      await refresh()
      Modal.info({
        title: approved ? 'Action executed' : 'Clarification sent',
        content: <Paragraph style={{ marginBottom: 0 }}>{updated.final_answer}</Paragraph>,
      })
    } catch (e) {
      message.error(e.message)
    } finally {
      setDeciding(false)
    }
  }

  const stats = useMemo(() => {
    const total = runs.length
    const pending = runs.filter((r) => r.status === 'awaiting_approval').length
    const done = runs.filter((r) => r.status === 'completed').length
    return { total, pending, done }
  }, [runs])

  const columns = [
    { title: 'Run', dataIndex: 'thread_id', width: 120, render: (v) => <Text code>{v}</Text> },
    { title: 'Ticket', dataIndex: 'query', ellipsis: true },
    { title: 'Route', dataIndex: 'route', width: 130, render: (r) => <RouteTag route={r} /> },
    {
      title: 'Status',
      dataIndex: 'status',
      width: 190,
      render: (s) => <StatusBadge status={s} />,
    },
    {
      title: 'Result',
      dataIndex: 'final_answer',
      ellipsis: true,
      render: (a, row) =>
        row.status === 'awaiting_approval' ? (
          <Text type="warning">Needs review</Text>
        ) : (
          <Tooltip title={a}>
            <Text type="secondary">{a || '—'}</Text>
          </Tooltip>
        ),
    },
    {
      title: 'Action',
      width: 130,
      render: (_, row) =>
        row.status === 'awaiting_approval' ? (
          <Button type="primary" size="small" danger onClick={() => setReview(row)}>
            Review
          </Button>
        ) : null,
    },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: '#141029',
          paddingInline: 24,
        }}
      >
        <Space align="center">
          <PartitionOutlined style={{ color: '#b794f6', fontSize: 22 }} />
          <span style={{ color: '#fff', fontSize: 18, fontWeight: 600 }}>
            LangGraph · HITL Support Console
          </span>
        </Space>
        <Space>
          <Button ghost icon={<ApartmentOutlined />} onClick={() => setGraphOpen(true)}>
            View graph
          </Button>
          <Button ghost icon={<ReloadOutlined />} onClick={refresh}>
            Refresh
          </Button>
        </Space>
      </Header>

      <Content style={{ padding: 24, maxWidth: 1200, width: '100%', margin: '0 auto' }}>
        <Flex gap={16} wrap="wrap" style={{ marginBottom: 16 }}>
          <Card style={{ flex: 1, minWidth: 160 }}>
            <Statistic title="Total runs" value={stats.total} />
          </Card>
          <Card style={{ flex: 1, minWidth: 160 }}>
            <Statistic
              title="Awaiting approval"
              value={stats.pending}
              valueStyle={{ color: stats.pending ? '#d48806' : undefined }}
              prefix={<SafetyCertificateOutlined />}
            />
          </Card>
          <Card style={{ flex: 1, minWidth: 160 }}>
            <Statistic
              title="Completed"
              value={stats.done}
              valueStyle={{ color: '#389e0d' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Flex>

        <Card title="New support ticket" style={{ marginBottom: 16 }}>
          <Input.TextArea
            rows={3}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. Refund this customer and send confirmation email"
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
          />
          <Flex justify="space-between" align="center" wrap="wrap" gap={8} style={{ marginTop: 12 }}>
            <Space wrap size={[4, 4]}>
              {examples.map((ex) => (
                <Button key={ex.label} size="small" onClick={() => setQuery(ex.query)}>
                  {ex.label}
                </Button>
              ))}
            </Space>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={submitting}
              onClick={submit}
            >
              Run through graph
            </Button>
          </Flex>
        </Card>

        <Card title="Runs">
          <Table
            rowKey="thread_id"
            columns={columns}
            dataSource={runs}
            pagination={false}
            locale={{ emptyText: <Empty description="No runs yet — submit a ticket above" /> }}
            rowClassName={(r) => (r.status === 'awaiting_approval' ? 'row-pending' : '')}
          />
        </Card>
      </Content>

      <Modal
        title={
          <Space>
            <SafetyCertificateOutlined style={{ color: '#d48806' }} />
            Human approval required
          </Space>
        }
        open={!!review}
        onCancel={() => setReview(null)}
        footer={[
          <Button
            key="reject"
            danger
            icon={<CloseCircleOutlined />}
            loading={deciding}
            onClick={() => submitDecision(false)}
          >
            Reject
          </Button>,
          <Button
            key="approve"
            type="primary"
            icon={<CheckCircleOutlined />}
            loading={deciding}
            onClick={() => submitDecision(true)}
          >
            Approve & execute
          </Button>,
        ]}
      >
        {review && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <div>
              <Text type="secondary">Ticket</Text>
              <Paragraph strong style={{ marginBottom: 8 }}>
                {review.query}
              </Paragraph>
            </div>
            <Alert
              type="warning"
              showIcon
              message="Proposed high-risk action"
              description={review.proposed_action}
            />
            <Text type="secondary">
              The graph is paused at the <Text code>approval</Text> node via{' '}
              <Text code>interrupt()</Text>. Your decision resumes it.
            </Text>
          </Space>
        )}
      </Modal>

      <GraphDrawer open={graphOpen} onClose={() => setGraphOpen(false)} />
    </Layout>
  )
}

// Root: ConfigProvider (theme) + antd App (message/modal context) wrap the console.
export default function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: { colorPrimary: '#6d28d9', borderRadius: 8 },
      }}
    >
      <AntApp>
        <Console />
      </AntApp>
    </ConfigProvider>
  )
}
