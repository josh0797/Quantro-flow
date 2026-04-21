import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Separator } from '../components/ui/separator';
import { Skeleton } from '../components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Textarea } from '../components/ui/textarea';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '../components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import {
  PenTool, Sparkles, Loader2, Trash2, Copy, Instagram, Mail, Linkedin, Hash,
  FileText, Plus, Edit3, Wand2, BookTemplate, ArrowRight
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  getContent, generateContent, deleteContent,
  getTemplates, createTemplate, deleteTemplate, generateFromTemplate
} from '../lib/api';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';
import { useBusinessProfile } from '../contexts/BusinessProfileContext';
import { useLanguage } from '../context/LanguageContext';

const categoryLabels = {
  welcome: { label: 'Welcome', color: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' },
  follow_up: { label: 'Follow-up', color: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]' },
  recruiting: { label: 'Recruiting', color: 'bg-[hsl(var(--info)/0.15)] text-[hsl(var(--info))]' },
  social: { label: 'Social', color: 'bg-[hsl(var(--accent)/0.15)] text-[hsl(var(--accent))]' },
  market_update: { label: 'Market Update', color: 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]' },
};

export default function ContentEngine() {
  const { profile } = useBusinessProfile();
  const { t } = useLanguage();
  const industry = profile?.industry || 'other';
  
  const [content, setContent] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [filter, setFilter] = useState('all');
  const [previewItem, setPreviewItem] = useState(null);
  const [mainTab, setMainTab] = useState('content');

  // Template state
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false);
  const [templateForm, setTemplateForm] = useState({ name: '', category: 'welcome', template_type: 'email', subject_template: '', body_template: '', variables: '', tags: '' });
  const [savingTemplate, setSavingTemplate] = useState(false);

  // Generate from template state
  const [genDialogOpen, setGenDialogOpen] = useState(false);
  const [genTemplate, setGenTemplate] = useState(null);
  const [genContext, setGenContext] = useState({});
  const [genPreview, setGenPreview] = useState('');
  const [generatingFromTemplate, setGeneratingFromTemplate] = useState(false);

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

  const fetchTemplates = useCallback(async () => {
    try {
      const data = await getTemplates();
      setTemplates(data);
    } catch (err) {
      console.error(err);
    }
  }, []);

  useEffect(() => { fetchContent(); fetchTemplates(); }, [fetchContent, fetchTemplates, profile?.simulation_mode]);

  const handleGenerate = async () => {
    if (!prompt.trim()) {
      toast.error(t('content_engine.toasts.generate_failed'));
      return;
    }
    setGenerating(true);
    try {
      const result = await generateContent({ prompt, type: 'both' });
      toast.success(t('content_engine.toasts.generated'), { description: `${result.items.length} item(s)` });
      setPrompt('');
      fetchContent();
    } catch (err) {
      toast.error(t('content_engine.toasts.generate_failed'), { description: err.response?.data?.detail || err.message });
    } finally {
      setGenerating(false);
    }
  };

  const handleDelete = async (contentId) => {
    try {
      await deleteContent(contentId);
      toast.success(t('content_engine.toasts.template_deleted'));
      fetchContent();
      if (previewItem?.content_id === contentId) setPreviewItem(null);
    } catch (err) {
      toast.error(t('content_engine.toasts.save_failed'));
    }
  };

  const handleCopy = (text) => {
    navigator.clipboard.writeText(text);
    toast.success('Copied to clipboard');
  };

  const handleCreateTemplate = async () => {
    if (!templateForm.name || !templateForm.body_template) {
      toast.error(t('content_engine.toasts.save_failed'));
      return;
    }
    setSavingTemplate(true);
    try {
      await createTemplate({
        ...templateForm,
        variables: templateForm.variables ? templateForm.variables.split(',').map(s => s.trim()) : [],
        tags: templateForm.tags ? templateForm.tags.split(',').map(s => s.trim()) : [],
      });
      toast.success(t('content_engine.toasts.template_saved'));
      setTemplateDialogOpen(false);
      setTemplateForm({ name: '', category: 'welcome', template_type: 'email', subject_template: '', body_template: '', variables: '', tags: '' });
      fetchTemplates();
    } catch (err) {
      toast.error('Failed to create template');
    } finally {
      setSavingTemplate(false);
    }
  };

  const handleDeleteTemplate = async (templateId) => {
    try {
      await deleteTemplate(templateId);
      toast.success('Template deleted');
      fetchTemplates();
      if (selectedTemplate?.template_id === templateId) setSelectedTemplate(null);
    } catch (err) {
      toast.error(t('content_engine.toasts.save_failed'));
    }
  };

  const openGenerateDialog = (template) => {
    setGenTemplate(template);
    const ctx = {};
    (template.variables || []).forEach(v => { ctx[v] = ''; });
    setGenContext(ctx);
    // Build preview
    let preview = template.body_template;
    (template.variables || []).forEach(v => {
      preview = preview.replace(new RegExp(`\\{\\{${v}\\}\\}`, 'g'), `[${v}]`);
    });
    setGenPreview(preview);
    setGenDialogOpen(true);
  };

  const updateGenContext = (key, value) => {
    const newCtx = { ...genContext, [key]: value };
    setGenContext(newCtx);
    // Update preview
    if (genTemplate) {
      let preview = genTemplate.body_template;
      Object.entries(newCtx).forEach(([k, v]) => {
        preview = preview.replace(new RegExp(`\\{\\{${k}\\}\\}`, 'g'), v || `[${k}]`);
      });
      setGenPreview(preview);
    }
  };

  const handleGenerateFromTemplate = async () => {
    if (!genTemplate) return;
    setGeneratingFromTemplate(true);
    try {
      const result = await generateFromTemplate(genTemplate.template_id, genContext);
      toast.success(t('content_engine.toasts.generated'), {
        description: result.enhanced ? 'AI-enhanced version created' : 'Template filled with your content'
      });
      setGenDialogOpen(false);
      fetchContent();
    } catch (err) {
      toast.error(t('content_engine.toasts.generate_failed'), { description: err.response?.data?.detail || err.message });
    } finally {
      setGeneratingFromTemplate(false);
    }
  };

  const socialPosts = content.filter(c => c.type === 'social_post');
  const emailDrafts = content.filter(c => c.type === 'email_draft');

  return (
    <div className="page-container relative z-[1]">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">{t('content_engine.title')}</h1>
          <p className="text-sm text-muted-foreground mt-1">AI-powered content generation and template management</p>
        </div>
        <Badge variant="secondary" className="text-xs">{content.length} items | {templates.length} templates</Badge>
      </div>

      <Tabs value={mainTab} onValueChange={setMainTab}>
        <TabsList className="mb-6">
          <TabsTrigger value="content" className="gap-1.5">
            <PenTool size={14} /> Content Library
          </TabsTrigger>
          <TabsTrigger value="templates" className="gap-1.5">
            <FileText size={14} /> Templates
          </TabsTrigger>
        </TabsList>

        {/* Content Library Tab */}
        <TabsContent value="content">
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
                <ContentPreview item={previewItem} onCopy={handleCopy} />
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
        </TabsContent>

        {/* Templates Tab */}
        <TabsContent value="templates">
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-muted-foreground">Reusable templates for consistent, on-brand communication</p>
            <Dialog open={templateDialogOpen} onOpenChange={setTemplateDialogOpen}>
              <DialogTrigger asChild>
                <Button data-testid="create-template-button" size="sm">
                  <Plus size={14} className="mr-1" /> Create Template
                </Button>
              </DialogTrigger>
              <DialogContent className="bg-[hsl(var(--card))] border-[hsl(var(--border))] max-w-2xl">
                <DialogHeader><DialogTitle>Create Template</DialogTitle></DialogHeader>
                <div className="space-y-4 py-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div><Label>Name *</Label><Input value={templateForm.name} onChange={e => setTemplateForm({...templateForm, name: e.target.value})} placeholder="e.g. Welcome Email" /></div>
                    <div><Label>Category</Label>
                      <Select value={templateForm.category} onValueChange={v => setTemplateForm({...templateForm, category: v})}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="welcome">Welcome</SelectItem>
                          <SelectItem value="follow_up">Follow-up</SelectItem>
                          <SelectItem value="recruiting">Recruiting</SelectItem>
                          <SelectItem value="social">Social</SelectItem>
                          <SelectItem value="market_update">Market Update</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <div><Label>Type</Label>
                    <Select value={templateForm.template_type} onValueChange={v => setTemplateForm({...templateForm, template_type: v})}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="email">Email Draft</SelectItem>
                        <SelectItem value="social_post">Social Post</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  {templateForm.template_type === 'email' && (
                    <div><Label>Subject Template</Label><Input value={templateForm.subject_template} onChange={e => setTemplateForm({...templateForm, subject_template: e.target.value})} placeholder="Use {{variable}} for dynamic values" /></div>
                  )}
                  <div><Label>Body Template *</Label>
                    <Textarea
                      value={templateForm.body_template}
                      onChange={e => setTemplateForm({...templateForm, body_template: e.target.value})}
                      placeholder="Write your template body. Use {{contact_name}}, {{situation}} etc. for dynamic values."
                      className="min-h-[120px]"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div><Label>Variables</Label><Input value={templateForm.variables} onChange={e => setTemplateForm({...templateForm, variables: e.target.value})} placeholder="contact_name, situation" /><p className="text-[10px] text-muted-foreground mt-1">Comma-separated variable names</p></div>
                    <div><Label>Tags</Label><Input value={templateForm.tags} onChange={e => setTemplateForm({...templateForm, tags: e.target.value})} placeholder="onboarding, welcome" /><p className="text-[10px] text-muted-foreground mt-1">Comma-separated tags</p></div>
                  </div>
                </div>
                <DialogFooter>
                  <Button variant="secondary" onClick={() => setTemplateDialogOpen(false)}>Cancel</Button>
                  <Button onClick={handleCreateTemplate} disabled={savingTemplate}>
                    {savingTemplate ? <Loader2 size={14} className="animate-spin mr-1" /> : <Plus size={14} className="mr-1" />}
                    Create Template
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>

          <div className="grid lg:grid-cols-5 gap-6">
            <div className="lg:col-span-3">
              <div data-testid="template-library" className="space-y-2">
                {templates.length === 0 ? (
                  <Card className="py-12">
                    <CardContent className="text-center">
                      <FileText size={32} className="mx-auto text-muted-foreground mb-3" />
                      <p className="text-sm text-muted-foreground">No templates yet. Create one to get started.</p>
                    </CardContent>
                  </Card>
                ) : (
                  templates.map((template, i) => {
                    const catInfo = categoryLabels[template.category] || { label: template.category, color: '' };
                    return (
                      <motion.div key={template.template_id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
                        <div
                          data-testid="template-card"
                          className={`p-4 rounded-xl border cursor-pointer transition-all group ${
                            selectedTemplate?.template_id === template.template_id
                              ? 'bg-[hsl(var(--surface-2))] border-[hsl(var(--ring)/0.3)]'
                              : 'bg-[hsl(var(--surface-1))] border-[hsl(var(--border))] hover:bg-[hsl(var(--surface-2))]'
                          }`}
                          onClick={() => setSelectedTemplate(template)}
                        >
                          <div className="flex items-start justify-between mb-2">
                            <div className="flex items-center gap-2">
                              <FileText size={14} className="text-muted-foreground" />
                              <Badge className={`text-[10px] ${catInfo.color}`}>{catInfo.label}</Badge>
                              <Badge variant="secondary" className="text-[10px] capitalize">{template.template_type === 'email' ? 'Email' : 'Social'}</Badge>
                            </div>
                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 text-xs"
                                onClick={(e) => { e.stopPropagation(); openGenerateDialog(template); }}
                              >
                                <Wand2 size={12} className="mr-1" /> Generate
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                                onClick={(e) => { e.stopPropagation(); handleDeleteTemplate(template.template_id); }}
                              >
                                <Trash2 size={12} />
                              </Button>
                            </div>
                          </div>
                          <p className="text-sm font-medium">{template.name}</p>
                          <p className="text-xs text-muted-foreground line-clamp-2 mt-1">{template.body_template}</p>
                          {template.variables?.length > 0 && (
                            <div className="flex gap-1 mt-2">
                              {template.variables.map((v, idx) => (
                                <Badge key={idx} variant="secondary" className="text-[9px] font-mono">{`{{${v}}}`}</Badge>
                              ))}
                            </div>
                          )}
                        </div>
                      </motion.div>
                    );
                  })
                )}
              </div>
            </div>

            {/* Template Preview */}
            <div className="lg:col-span-2">
              {selectedTemplate ? (
                <Card>
                  <CardHeader>
                    <div className="flex items-start justify-between">
                      <div>
                        <Badge className={`text-xs mb-2 ${categoryLabels[selectedTemplate.category]?.color || ''}`}>
                          {categoryLabels[selectedTemplate.category]?.label || selectedTemplate.category}
                        </Badge>
                        <CardTitle className="text-base">{selectedTemplate.name}</CardTitle>
                      </div>
                      <Button
                        data-testid="template-generate-button"
                        size="sm"
                        onClick={() => openGenerateDialog(selectedTemplate)}
                      >
                        <Wand2 size={14} className="mr-1" /> Generate with AI
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {selectedTemplate.subject_template && (
                      <div className="mb-4">
                        <p className="text-xs text-muted-foreground mb-1">Subject Template</p>
                        <p className="text-sm font-mono bg-[hsl(var(--surface-1))] p-2 rounded border border-[hsl(var(--border))]">{selectedTemplate.subject_template}</p>
                      </div>
                    )}
                    <div className="mb-4">
                      <p className="text-xs text-muted-foreground mb-1">Body Template</p>
                      <div className="p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                        <p className="text-sm leading-relaxed whitespace-pre-wrap font-mono">{selectedTemplate.body_template}</p>
                      </div>
                    </div>
                    {selectedTemplate.variables?.length > 0 && (
                      <div className="mb-4">
                        <p className="text-xs text-muted-foreground mb-2">Variables</p>
                        <div className="flex flex-wrap gap-2">
                          {selectedTemplate.variables.map((v, i) => (
                            <Badge key={i} variant="secondary" className="font-mono text-xs">{`{{${v}}}`}</Badge>
                          ))}
                        </div>
                      </div>
                    )}
                    {selectedTemplate.tags?.length > 0 && (
                      <div>
                        <p className="text-xs text-muted-foreground mb-2">Tags</p>
                        <div className="flex flex-wrap gap-2">
                          {selectedTemplate.tags.map((tag, i) => (
                            <Badge key={i} variant="secondary" className="text-xs">
                              <Hash size={10} className="mr-1" />{tag}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              ) : (
                <Card className="h-full flex items-center justify-center min-h-[300px]">
                  <CardContent className="text-center">
                    <FileText size={32} className="mx-auto text-muted-foreground mb-3" />
                    <p className="text-sm text-muted-foreground">Select a template to preview</p>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </TabsContent>
      </Tabs>

      {/* Generate from Template Dialog */}
      <Dialog open={genDialogOpen} onOpenChange={setGenDialogOpen}>
        <DialogContent className="bg-[hsl(var(--card))] border-[hsl(var(--border))] max-w-3xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Wand2 size={18} className="text-[hsl(var(--primary))]" />
              Generate from Template: {genTemplate?.name}
            </DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-6 py-4">
            {/* Left: Variables */}
            <div className="space-y-4">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Fill in context</p>
              {genTemplate?.variables?.map(variable => (
                <div key={variable}>
                  <Label className="capitalize">{variable.replace(/_/g, ' ')}</Label>
                  <Input
                    data-testid={`template-var-${variable}`}
                    value={genContext[variable] || ''}
                    onChange={e => updateGenContext(variable, e.target.value)}
                    placeholder={`Enter ${variable.replace(/_/g, ' ')}...`}
                  />
                </div>
              ))}
              {(!genTemplate?.variables || genTemplate.variables.length === 0) && (
                <p className="text-sm text-muted-foreground">This template has no variables. Click Generate to create AI-enhanced content.</p>
              )}
            </div>

            {/* Right: Live Preview */}
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Live Preview</p>
              <div className="p-4 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))] min-h-[200px]">
                <p className="text-sm leading-relaxed whitespace-pre-wrap">{genPreview}</p>
              </div>
              <p className="text-[10px] text-muted-foreground mt-2">AI will enhance the final version while keeping your structure</p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setGenDialogOpen(false)}>Cancel</Button>
            <Button
              data-testid="template-generate-submit"
              onClick={handleGenerateFromTemplate}
              disabled={generatingFromTemplate}
            >
              {generatingFromTemplate ? (
                <><Loader2 size={14} className="animate-spin mr-1.5" /> Generating...</>
              ) : (
                <><Wand2 size={14} className="mr-1.5" /> Generate with AI</>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ─── ContentGrid Component ───────────────────────────────────────────
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
                  {item.created_by === 'ai_template' && (
                    <Badge className="text-[10px] bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]">From Template</Badge>
                  )}
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

// ─── ContentPreview Component ────────────────────────────────────────
function ContentPreview({ item, onCopy }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <Badge variant="secondary" className="text-xs capitalize mb-2">
              {item.type === 'social_post' ? 'Social Post' : 'Email Draft'}
            </Badge>
            <CardTitle className="text-base">{item.title}</CardTitle>
          </div>
          <Badge className={`text-xs ${item.status === 'published' ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' : 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]'}`}>
            {item.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {item.type === 'social_post' ? (
          <div className="space-y-4">
            <div className="p-4 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
              <p className="text-sm leading-relaxed">{item.content?.text}</p>
            </div>
            {item.content?.hashtags && (
              <div className="flex flex-wrap gap-2">
                {item.content.hashtags.map((tag, i) => (
                  <Badge key={i} variant="secondary" className="text-xs">
                    <Hash size={10} className="mr-1" />{tag.replace('#', '')}
                  </Badge>
                ))}
              </div>
            )}
            <Button size="sm" variant="secondary" onClick={() => onCopy(item.content?.text || '')}>
              <Copy size={14} className="mr-1" /> Copy Text
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <p className="text-xs text-muted-foreground mb-1">Subject</p>
              <p className="text-sm font-medium">{item.content?.subject}</p>
            </div>
            <div className="p-4 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{item.content?.body}</p>
            </div>
            {item.content?.call_to_action && (
              <div className="p-3 rounded-lg bg-[hsl(var(--primary)/0.08)] border border-[hsl(var(--primary)/0.2)]">
                <p className="text-xs text-muted-foreground mb-1">Call to Action</p>
                <p className="text-sm font-medium">{item.content.call_to_action}</p>
              </div>
            )}
            <Button size="sm" variant="secondary" onClick={() => onCopy(item.content?.body || '')}>
              <Copy size={14} className="mr-1" /> Copy Body
            </Button>
          </div>
        )}
        <Separator className="my-4" />
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-mono text-muted-foreground">
            Created {(() => { try { return format(parseISO(item.created_at), 'MMM d, yyyy HH:mm'); } catch { return ''; } })()}
            {' '}by {item.created_by}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
