import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Separator } from '../components/ui/separator';
import { Skeleton } from '../components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Textarea } from '../components/ui/textarea';
import { PenTool, Sparkles, Loader2, Trash2, Copy, Instagram, Mail, Linkedin, Hash } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { getContent, generateContent, deleteContent } from '../lib/api';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';

const platformIcons = {
  instagram: Instagram,
  linkedin: Linkedin,
};

export default function ContentEngine() {
  const [content, setContent] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [filter, setFilter] = useState('all');
  const [previewItem, setPreviewItem] = useState(null);

  const fetchContent = useCallback(async () => {
    try {
      const data = await getContent(filter === 'all' ? null : filter);
      setContent(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { fetchContent(); }, [fetchContent]);

  const handleGenerate = async () => {
    if (!prompt.trim()) {
      toast.error('Please enter a prompt');
      return;
    }
    setGenerating(true);
    try {
      const result = await generateContent({ prompt, type: 'both' });
      toast.success('Content generated', { description: `${result.items.length} item(s) created` });
      setPrompt('');
      fetchContent();
    } catch (err) {
      toast.error('Generation failed', { description: err.response?.data?.detail || err.message });
    } finally {
      setGenerating(false);
    }
  };

  const handleDelete = async (contentId) => {
    try {
      await deleteContent(contentId);
      toast.success('Content deleted');
      fetchContent();
      if (previewItem?.content_id === contentId) setPreviewItem(null);
    } catch (err) {
      toast.error('Delete failed');
    }
  };

  const handleCopy = (text) => {
    navigator.clipboard.writeText(text);
    toast.success('Copied to clipboard');
  };

  const socialPosts = content.filter(c => c.type === 'social_post');
  const emailDrafts = content.filter(c => c.type === 'email_draft');

  return (
    <div className="page-container relative z-[1]">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">Content Engine</h1>
          <p className="text-sm text-muted-foreground mt-1">AI-powered content generation for your real estate marketing</p>
        </div>
        <Badge variant="secondary" className="text-xs">{content.length} items</Badge>
      </div>

      {/* Generation Panel */}
      <Card className="mb-6">
        <CardContent className="p-5">
          <div className="flex items-start gap-2">
            <Sparkles size={18} className="text-[hsl(var(--primary))] mt-2 shrink-0" />
            <div className="flex-1">
              <Textarea
                data-testid="content-engine-prompt-textarea"
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                placeholder="Describe the content you want to generate... e.g., 'New luxury listing: 5-bedroom waterfront estate at $2.8M with infinity pool and smart home'"
                className="min-h-[80px] bg-[hsl(var(--surface-1))] border-[hsl(var(--border))] resize-none"
              />
              <div className="flex items-center justify-between mt-3">
                <p className="text-xs text-muted-foreground">AI will generate both a social post and email draft</p>
                <Button
                  data-testid="content-engine-generate-button"
                  onClick={handleGenerate}
                  disabled={generating || !prompt.trim()}
                  size="sm"
                >
                  {generating ? (
                    <><Loader2 size={14} className="animate-spin mr-1" /> Generating...</>
                  ) : (
                    <><PenTool size={14} className="mr-1" /> Generate</>
                  )}
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Content Grid */}
      <div className="grid lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3">
          <Tabs defaultValue="all" onValueChange={v => { setFilter(v); setLoading(true); }}>
            <TabsList className="mb-4">
              <TabsTrigger value="all">All ({content.length})</TabsTrigger>
              <TabsTrigger value="social_post">Social ({socialPosts.length})</TabsTrigger>
              <TabsTrigger value="email_draft">Email ({emailDrafts.length})</TabsTrigger>
            </TabsList>

            <TabsContent value="all">
              <ContentGrid items={content} onSelect={setPreviewItem} onDelete={handleDelete} selectedId={previewItem?.content_id} />
            </TabsContent>
            <TabsContent value="social_post">
              <ContentGrid items={socialPosts} onSelect={setPreviewItem} onDelete={handleDelete} selectedId={previewItem?.content_id} />
            </TabsContent>
            <TabsContent value="email_draft">
              <ContentGrid items={emailDrafts} onSelect={setPreviewItem} onDelete={handleDelete} selectedId={previewItem?.content_id} />
            </TabsContent>
          </Tabs>
        </div>

        {/* Preview Panel */}
        <div className="lg:col-span-2">
          {previewItem ? (
            <Card>
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div>
                    <Badge variant="secondary" className="text-xs capitalize mb-2">
                      {previewItem.type === 'social_post' ? 'Social Post' : 'Email Draft'}
                    </Badge>
                    <CardTitle className="text-base">{previewItem.title}</CardTitle>
                  </div>
                  <Badge className={`text-xs ${previewItem.status === 'published' ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' : 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]'}`}>
                    {previewItem.status}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                {previewItem.type === 'social_post' ? (
                  <div className="space-y-4">
                    <div className="p-4 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                      <p className="text-sm leading-relaxed">{previewItem.content?.text}</p>
                    </div>
                    {previewItem.content?.hashtags && (
                      <div className="flex flex-wrap gap-2">
                        {previewItem.content.hashtags.map((tag, i) => (
                          <Badge key={i} variant="secondary" className="text-xs">
                            <Hash size={10} className="mr-1" />{tag.replace('#', '')}
                          </Badge>
                        ))}
                      </div>
                    )}
                    <Button size="sm" variant="secondary" onClick={() => handleCopy(previewItem.content?.text || '')}>
                      <Copy size={14} className="mr-1" /> Copy Text
                    </Button>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Subject</p>
                      <p className="text-sm font-medium">{previewItem.content?.subject}</p>
                    </div>
                    <div className="p-4 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                      <p className="text-sm leading-relaxed whitespace-pre-wrap">{previewItem.content?.body}</p>
                    </div>
                    {previewItem.content?.call_to_action && (
                      <div className="p-3 rounded-lg bg-[hsl(var(--primary)/0.08)] border border-[hsl(var(--primary)/0.2)]">
                        <p className="text-xs text-muted-foreground mb-1">Call to Action</p>
                        <p className="text-sm font-medium">{previewItem.content.call_to_action}</p>
                      </div>
                    )}
                    <Button size="sm" variant="secondary" onClick={() => handleCopy(previewItem.content?.body || '')}>
                      <Copy size={14} className="mr-1" /> Copy Body
                    </Button>
                  </div>
                )}
                <Separator className="my-4" />
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono text-muted-foreground">
                    Created {(() => { try { return format(parseISO(previewItem.created_at), 'MMM d, yyyy HH:mm'); } catch { return ''; } })()}
                    {' '}by {previewItem.created_by}
                  </span>
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card className="h-full flex items-center justify-center min-h-[300px]">
              <CardContent className="text-center">
                <PenTool size={32} className="mx-auto text-muted-foreground mb-3" />
                <p className="text-sm text-muted-foreground">Select content to preview</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function ContentGrid({ items, onSelect, onDelete, selectedId }) {
  if (items.length === 0) {
    return (
      <div className="text-center py-12">
        <PenTool size={32} className="mx-auto text-muted-foreground mb-3" />
        <p className="text-sm text-muted-foreground">No content yet. Generate some using the prompt above.</p>
      </div>
    );
  }

  return (
    <div data-testid="content-engine-drafts-grid" className="space-y-2">
      <AnimatePresence>
        {items.map((item, i) => (
          <motion.div
            key={item.content_id}
            data-testid="content-engine-draft-item"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.03 }}
          >
            <div
              className={`p-4 rounded-xl border cursor-pointer transition-colors group ${
                selectedId === item.content_id
                  ? 'bg-[hsl(var(--surface-2))] border-[hsl(var(--ring)/0.3)]'
                  : 'bg-[hsl(var(--surface-1))] border-[hsl(var(--border))] hover:bg-[hsl(var(--surface-2))]'
              }`}
              onClick={() => onSelect(item)}
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  {item.type === 'social_post' ? (
                    <Instagram size={14} className="text-[hsl(var(--info))]" />
                  ) : (
                    <Mail size={14} className="text-[hsl(var(--warning))]" />
                  )}
                  <Badge variant="secondary" className="text-[10px] capitalize">
                    {item.type === 'social_post' ? 'Social' : 'Email'}
                  </Badge>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="opacity-0 group-hover:opacity-100 transition-opacity h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                  onClick={(e) => { e.stopPropagation(); onDelete(item.content_id); }}
                >
                  <Trash2 size={12} />
                </Button>
              </div>
              <p className="text-sm font-medium truncate">{item.title}</p>
              <p className="text-xs text-muted-foreground line-clamp-2 mt-1">
                {item.type === 'social_post' ? item.content?.text : item.content?.body}
              </p>
              <div className="flex items-center justify-between mt-2">
                <Badge className={`text-[10px] ${item.status === 'published' ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' : 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))]'}`}>
                  {item.status}
                </Badge>
                <span className="text-[10px] font-mono text-muted-foreground">
                  {(() => { try { return format(parseISO(item.created_at), 'MMM d'); } catch { return ''; } })()}
                </span>
              </div>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
