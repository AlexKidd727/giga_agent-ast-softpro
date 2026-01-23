import React, { useState, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useRagContext } from "@/components/rag/providers/RAG";
import { getCollectionName } from "@/components/rag/hooks/use-rag";
import { Upload, File, X, Tag, Search, Plus, Edit } from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

interface KnowledgeFile {
  path: string;
  full_path: string;
  name: string;
  size: number;
  file_type: string;
  mime_type: string;
  modified_at: string;
  description?: string;
  tags?: string[];
  category?: string;
  uploaded_at: string;
}

export const KnowledgeTab: React.FC = () => {
  const {
    collections,
    activeCollections,
    activateCollection,
    deactivateCollection,
    collectionsLoading,
  } = useRagContext();

  const [files, setFiles] = useState<KnowledgeFile[]>([]);
  const [filesLoading, setFilesLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingFile, setEditingFile] = useState<KnowledgeFile | null>(null);
  const [uploading, setUploading] = useState(false);
  const [updating, setUpdating] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Форма загрузки
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [category, setCategory] = useState("");

  // Форма редактирования
  const [editDescription, setEditDescription] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editCategory, setEditCategory] = useState("");

  const handleToggle = (collectionId: string, checked: boolean) => {
    if (checked) {
      activateCollection(collectionId);
    } else {
      deactivateCollection(collectionId);
    }
  };

  // Загрузка списка файлов
  const loadFiles = async () => {
    setFilesLoading(true);
    try {
      // Добавляем timestamp для предотвращения кэширования
      const timestamp = new Date().getTime();
      const response = await fetch(`/files/api/knowledge/files?t=${timestamp}`, {
        method: "GET",
        headers: {
          "Cache-Control": "no-cache, no-store, must-revalidate",
          "Pragma": "no-cache",
          "Expires": "0",
        },
      });
      if (!response.ok) {
        throw new Error("Ошибка при загрузке файлов");
      }
      const data = await response.json();
      setFiles(data.files || []);
    } catch (error) {
      console.error("Ошибка загрузки файлов:", error);
      toast.error("Не удалось загрузить список файлов");
    } finally {
      setFilesLoading(false);
    }
  };

  const [searchParams] = useSearchParams();
  const activeTab = searchParams.get("tab") || "tokens";

  // Загружаем файлы при монтировании и при открытии вкладки "knowledge"
  useEffect(() => {
    if (activeTab === "knowledge") {
      loadFiles();
    }
  }, [activeTab]);

  // Загрузка файла
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setUploadFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!uploadFile) {
      toast.error("Выберите файл для загрузки");
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      if (description) formData.append("description", description);
      if (tags) formData.append("tags", tags);
      if (category) formData.append("category", category);

      const response = await fetch("/files/api/knowledge/files/upload", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Ошибка при загрузке файла");
      }

      toast.success("Файл успешно загружен");
      setUploadDialogOpen(false);
      setUploadFile(null);
      setDescription("");
      setTags("");
      setCategory("");
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      await loadFiles();
    } catch (error: any) {
      console.error("Ошибка загрузки файла:", error);
      toast.error(error.message || "Не удалось загрузить файл");
    } finally {
      setUploading(false);
    }
  };

  // Открытие диалога редактирования
  const handleEditFile = (file: KnowledgeFile) => {
    setEditingFile(file);
    setEditDescription(file.description || "");
    setEditTags(file.tags?.join(", ") || "");
    setEditCategory(file.category || "");
    setEditDialogOpen(true);
  };

  // Сохранение изменений метаданных
  const handleUpdateMetadata = async () => {
    if (!editingFile) return;

    setUpdating(true);
    try {
      const formData = new FormData();
      if (editDescription !== editingFile.description) {
        formData.append("description", editDescription);
      }
      if (editTags !== editingFile.tags?.join(", ")) {
        formData.append("tags", editTags);
      }
      if (editCategory !== editingFile.category) {
        formData.append("category", editCategory);
      }

      const response = await fetch(
        `/files/api/knowledge/files/${encodeURIComponent(editingFile.path)}/metadata`,
        {
          method: "PUT",
          body: formData,
        }
      );

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Ошибка при обновлении метаданных");
      }

      toast.success("Метаданные успешно обновлены");
      setEditDialogOpen(false);
      setEditingFile(null);
      await loadFiles();
    } catch (error: any) {
      console.error("Ошибка обновления метаданных:", error);
      toast.error(error.message || "Не удалось обновить метаданные");
    } finally {
      setUpdating(false);
    }
  };

  // Фильтрация файлов
  const filteredFiles = files.filter((file) => {
    const matchesSearch =
      !searchQuery ||
      file.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      file.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      file.tags?.some((tag) => tag.toLowerCase().includes(searchQuery.toLowerCase()));

    const matchesCategory =
      selectedCategory === "all" || file.category === selectedCategory;

    return matchesSearch && matchesCategory;
  });

  // Получение уникальных категорий
  const categories = Array.from(
    new Set(files.map((f) => f.category).filter(Boolean))
  );

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} Б`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold mb-2">Знания</h3>
        <p className="text-sm text-muted-foreground">
          Активируйте коллекции из Базы Знаний и управляйте файлами в папке files
        </p>
      </div>

      {/* Коллекции RAG */}
      <div className="space-y-4">
        <div>
          <h4 className="text-md font-semibold">Коллекции RAG</h4>
          <p className="text-xs text-muted-foreground mt-1">
            Коллекции RAG загружаются из LangConnect API ({import.meta.env?.VITE_LANGCONNECT_API_URL || "не настроен"}).
            Это векторные базы знаний для семантического поиска по документам.
          </p>
        </div>
        {collectionsLoading && (
          <div className="text-sm text-muted-foreground">
            Загрузка коллекций…
          </div>
        )}
        {!collectionsLoading && collections.length === 0 && (
          <div className="text-sm text-muted-foreground space-y-2">
            <div>Коллекции не найдены.</div>
            <div className="text-xs">
              Проверьте настройки:
              <ul className="list-disc list-inside mt-1 space-y-1">
                <li>VITE_LANGCONNECT_API_URL должен быть установлен</li>
                <li>VITE_LANGCONNECT_API_SECRET_TOKEN должен быть установлен</li>
                <li>LangConnect API должен быть доступен и инициализирован</li>
              </ul>
            </div>
          </div>
        )}
        {!collectionsLoading &&
          collections.map((c) => {
            const enabled = Boolean(activeCollections[c.uuid]);
            return (
              <div
                key={c.uuid}
                className={`bg-card border rounded-lg p-4 ${enabled ? "" : "opacity-50"}`}
              >
                <div className="flex items-center justify-between">
                  <div className="min-w-0">
                    <div className="font-medium text-foreground truncate">
                      {getCollectionName(c.name)}
                    </div>
                    {c.metadata?.description && (
                      <div className="text-sm text-muted-foreground break-words">
                        {c.metadata.description}
                      </div>
                    )}
                  </div>
                  <Switch
                    checked={enabled}
                    onCheckedChange={(checked) =>
                      handleToggle(c.uuid, Boolean(checked))
                    }
                    aria-label={`Включить коллекцию ${c.name}`}
                  />
                </div>
              </div>
            );
          })}
      </div>

      {/* Файлы из папки files */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h4 className="text-md font-semibold">Файлы в папке files</h4>
          <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
            <DialogTrigger asChild>
              <Button size="sm" className="gap-2">
                <Plus className="h-4 w-4" />
                Загрузить файл
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Загрузить файл в базу знаний</DialogTitle>
                <DialogDescription>
                  Загрузите файл и добавьте описание для быстрого поиска
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="file">Файл</Label>
                  <Input
                    id="file"
                    type="file"
                    ref={fileInputRef}
                    onChange={handleFileSelect}
                  />
                  {uploadFile && (
                    <div className="mt-2 text-sm text-muted-foreground">
                      Выбран: {uploadFile.name} ({(uploadFile.size / 1024).toFixed(1)} КБ)
                    </div>
                  )}
                </div>
                <div>
                  <Label htmlFor="description">Описание файла</Label>
                  <Textarea
                    id="description"
                    placeholder="О чем этот файл? Что в нем содержится?"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={3}
                  />
                </div>
                <div>
                  <Label htmlFor="tags">Теги (через запятую)</Label>
                  <Input
                    id="tags"
                    placeholder="тег1, тег2, тег3"
                    value={tags}
                    onChange={(e) => setTags(e.target.value)}
                  />
                </div>
                <div>
                  <Label htmlFor="category">Категория</Label>
                  <Input
                    id="category"
                    placeholder="Например: документация, данные, отчеты"
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                  />
                </div>
                <Button
                  onClick={handleUpload}
                  disabled={!uploadFile || uploading}
                  className="w-full"
                >
                  {uploading ? "Загрузка..." : "Загрузить"}
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>

        {/* Поиск и фильтры */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Поиск по названию, описанию или тегам..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8"
            />
          </div>
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            className="px-3 py-2 border rounded-md bg-background"
          >
            <option value="all">Все категории</option>
            {categories.map((cat) => (
              <option key={cat} value={cat}>
                {cat}
              </option>
            ))}
          </select>
        </div>

        {/* Список файлов */}
        {filesLoading && (
          <div className="text-sm text-muted-foreground">Загрузка файлов…</div>
        )}
        {!filesLoading && filteredFiles.length === 0 && (
          <div className="text-sm text-muted-foreground">
            {files.length === 0
              ? "Файлы не найдены. Загрузите первый файл."
              : "Файлы не найдены по заданным критериям."}
          </div>
        )}
        {!filesLoading &&
          filteredFiles.map((file) => (
            <div
              key={file.full_path}
              className="bg-card border rounded-lg p-4 space-y-2"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <File className="h-5 w-5 text-muted-foreground mt-0.5 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-foreground truncate">
                      {file.name}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {formatFileSize(file.size)} • {file.file_type}
                    </div>
                    {file.description && (
                      <div className="text-sm text-foreground mt-1">
                        {file.description}
                      </div>
                    )}
                    {file.tags && file.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {file.tags.map((tag, idx) => (
                          <span
                            key={idx}
                            className="inline-flex items-center gap-1 px-2 py-0.5 text-xs bg-secondary rounded"
                          >
                            <Tag className="h-3 w-3" />
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                    {file.category && (
                      <div className="text-xs text-muted-foreground mt-1">
                        Категория: {file.category}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <a
                    href={`/files/${file.path}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-primary hover:underline"
                  >
                    Открыть
                  </a>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleEditFile(file)}
                    className="gap-1"
                  >
                    <Edit className="h-3 w-3" />
                    Редактировать
                  </Button>
                </div>
              </div>
            </div>
          ))}

        {/* Диалог редактирования метаданных */}
        <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Редактировать метаданные файла</DialogTitle>
              <DialogDescription>
                {editingFile?.name}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div>
                <Label htmlFor="edit-description">Описание файла</Label>
                <Textarea
                  id="edit-description"
                  placeholder="О чем этот файл? Что в нем содержится?"
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  rows={3}
                />
              </div>
              <div>
                <Label htmlFor="edit-tags">Теги (через запятую)</Label>
                <Input
                  id="edit-tags"
                  placeholder="тег1, тег2, тег3"
                  value={editTags}
                  onChange={(e) => setEditTags(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="edit-category">Категория</Label>
                <Input
                  id="edit-category"
                  placeholder="Например: документация, данные, отчеты"
                  value={editCategory}
                  onChange={(e) => setEditCategory(e.target.value)}
                />
              </div>
              <div className="flex gap-2">
                <Button
                  onClick={handleUpdateMetadata}
                  disabled={updating}
                  className="flex-1"
                >
                  {updating ? "Сохранение..." : "Сохранить"}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    setEditDialogOpen(false);
                    setEditingFile(null);
                  }}
                  disabled={updating}
                >
                  Отмена
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
};

