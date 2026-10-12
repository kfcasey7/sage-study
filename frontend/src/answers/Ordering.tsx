import { useEffect } from "react";
import {
  DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ChevronDown, ChevronUp, GripVertical } from "lucide-react";
import { MarkdownInline } from "../components/MarkdownInline";
import type { InputProps } from "./objective";

function Item({ id, text, index, count, locked, state, move }: {
  id: number; text: string; index: number; count: number; locked: boolean; state: string; move: (from: number, to: number) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id, disabled: locked });
  return (
    <div ref={setNodeRef} style={locked ? undefined : { transform: CSS.Transform.toString(transform), transition }}
      className={`sortable-item ${isDragging ? "dragging" : ""} ${state}`}>
      {!locked && <span className="handle" {...attributes} {...listeners} aria-label="Drag to reorder"><GripVertical size={18} /></span>}
      <span className="num">{index + 1}</span>
      <span style={{ flex: 1 }}><MarkdownInline>{text}</MarkdownInline></span>
      {!locked && (
        <span className="move">
          <button className="icon-btn" style={{ height: 20 }} disabled={index === 0} onClick={() => move(index, index - 1)} aria-label="Move up"><ChevronUp size={16} /></button>
          <button className="icon-btn" style={{ height: 20 }} disabled={index === count - 1} onClick={() => move(index, index + 1)} aria-label="Move down"><ChevronDown size={16} /></button>
        </span>
      )}
    </div>
  );
}

export function Ordering({ q, value, onChange, locked, answerKey }: InputProps) {
  const items = q.items!;
  const order = (value.order as number[] | undefined) ?? items.map((it) => it.id);
  const byId = new Map(items.map((it) => [it.id, it.text]));
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));

  // Record the initial (shuffled) order so submitting without changes is still a valid answer.
  useEffect(() => {
    if (!value.order) onChange({ order: items.map((it) => it.id) });
  }, [q.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function move(from: number, to: number) {
    onChange({ order: arrayMove(order, from, to) });
  }
  function onDragEnd(e: DragEndEvent) {
    if (!e.over || e.active.id === e.over.id) return;
    move(order.indexOf(Number(e.active.id)), order.indexOf(Number(e.over.id)));
  }
  return (
    <div>
      <div className="muted small" style={{ marginBottom: 8 }}>Drag the steps (or use the arrows) into the correct order, first at the top.</div>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={order} strategy={verticalListSortingStrategy}>
          {order.map((id, i) => (
            <Item key={id} id={id} text={byId.get(id) ?? ""} index={i} count={order.length} locked={locked} move={move}
              state={locked && answerKey?.order ? (answerKey.order[i] === id ? "correct" : "incorrect") : ""} />
          ))}
        </SortableContext>
      </DndContext>
      {locked && answerKey?.order && order.some((id, i) => answerKey.order![i] !== id) && (
        <div className="small muted" style={{ marginTop: 8 }}>
          Correct order: {answerKey.order.map((id) => byId.get(id)).join(" → ")}
        </div>
      )}
    </div>
  );
}
