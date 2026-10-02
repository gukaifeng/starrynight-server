import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";

type Shape = { name: string; mesh: THREE.Mesh; index: number };
export default function ModelPreview({
  url,
  name,
}: {
  url: string;
  name: string;
}) {
  const host = useRef<HTMLDivElement>(null),
    mixer = useRef<THREE.AnimationMixer | null>(null),
    clips = useRef<THREE.AnimationClip[]>([]),
    root = useRef<THREE.Object3D | null>(null);
  const [error, setError] = useState(""),
    [loaded, setLoaded] = useState(false),
    [stats, setStats] = useState({ meshes: 0, bones: 0, triangles: 0 }),
    [animations, setAnimations] = useState<string[]>([]),
    [shapes, setShapes] = useState<Shape[]>([]),
    [boneNames, setBoneNames] = useState<{ name: string; parent: string }[]>(
      [],
    ),
    [selected, setSelected] = useState(""),
    [wireframe, setWireframe] = useState(false);
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let stopped = false,
      frame = 0;
    let renderer: THREE.WebGLRenderer;
    setLoaded(false);
    setError("");
    setShapes([]);
    setBoneNames([]);
    setAnimations([]);
    setSelected("");
    setWireframe(false);
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setError("此浏览器暂不支持 WebGL 预览，可下载文件检查");
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor("#e9f0f1");
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const scene = new THREE.Scene(),
      camera = new THREE.PerspectiveCamera(35, 1, 0.01, 1000);
    camera.position.set(0, 1.3, 3);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x445565, 2.5));
    const light = new THREE.DirectionalLight(0xffffff, 3);
    light.position.set(3, 5, 4);
    scene.add(light);
    el.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    const resize = () => {
      const w = el.clientWidth,
        h = el.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();
    const manager = new THREE.LoadingManager();
    manager.setURLModifier((value) => {
      if (
        value === url ||
        value.startsWith("data:") ||
        value.startsWith("blob:")
      )
        return value;
      throw new Error(
        "模型引用了外部文件，请上传含嵌入贴图的 GLB 或 FBX 预览文件",
      );
    });
    const disposeObject = (object: THREE.Object3D) => {
      const textures = new Set<THREE.Texture>();
      object.traverse((o) => {
        const m = o as THREE.Mesh;
        if (!m.isMesh) return;
        m.geometry.dispose();
        for (const material of Array.isArray(m.material)
          ? m.material
          : [m.material]) {
          for (const value of Object.values(material))
            if (value instanceof THREE.Texture) textures.add(value);
          material.dispose();
        }
      });
      for (const texture of textures) texture.dispose();
    };
    const success = (model: THREE.Object3D, items: THREE.AnimationClip[]) => {
      if (stopped) {
        disposeObject(model);
        return;
      }
      root.current = model;
      scene.add(model);
      let meshes = 0,
        bones = 0,
        triangles = 0;
      const list: Shape[] = [];
      const skeleton: { name: string; parent: string }[] = [];
      model.traverse((object) => {
        if ((object as THREE.Bone).isBone) {
          bones++;
          skeleton.push({
            name: object.name || "未命名骨骼",
            parent: object.parent?.name ?? "根节点",
          });
        }
        const mesh = object as THREE.Mesh;
        if (!mesh.isMesh) return;
        meshes++;
        triangles +=
          (mesh.geometry.index?.count ??
            mesh.geometry.attributes.position?.count ??
            0) / 3;
        Object.entries(mesh.morphTargetDictionary ?? {}).forEach(
          ([name, index]) => list.push({ name, mesh, index }),
        );
      });
      const box = new THREE.Box3().setFromObject(model),
        size = box.getSize(new THREE.Vector3()),
        center = box.getCenter(new THREE.Vector3());
      const span = Math.max(size.x, size.y, size.z, 0.1);
      controls.target.copy(center);
      camera.position
        .copy(center)
        .add(new THREE.Vector3(span * 0.15, span * 0.08, span * 1.8));
      camera.near = span / 1000;
      camera.far = span * 100;
      camera.updateProjectionMatrix();
      controls.update();
      clips.current = items;
      mixer.current = new THREE.AnimationMixer(model);
      setAnimations(items.map((c, i) => c.name || "动画 " + (i + 1)));
      setShapes(list);
      setBoneNames(skeleton);
      setStats({ meshes, bones, triangles: Math.round(triangles) });
      setLoaded(true);
    };
    const failure = (reason: unknown) => {
      if (!stopped)
        setError(
          reason instanceof Error
            ? reason.message
            : "模型格式解析失败，请检查文件与完整性",
        );
    };
    const ext = name.toLowerCase().split(".").pop();
    try {
      if (ext === "fbx")
        new FBXLoader(manager).load(
          url,
          (m) => success(m, m.animations),
          undefined,
          failure,
        );
      else
        new GLTFLoader(manager).load(
          url,
          (g) => success(g.scene, g.animations),
          undefined,
          failure,
        );
    } catch (e) {
      failure(e);
    }
    const timer = new THREE.Clock();
    const animate = () => {
      if (stopped) return;
      mixer.current?.update(Math.min(timer.getDelta(), 0.05));
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    };
    animate();
    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      mixer.current?.stopAllAction();
      mixer.current = null;
      disposeObject(scene);
      renderer.dispose();
      renderer.domElement.remove();
      root.current = null;
    };
  }, [url, name]);
  const changeClip = (index: string) => {
    setSelected(index);
    mixer.current?.stopAllAction();
    if (index !== "" && clips.current[Number(index)])
      mixer.current?.clipAction(clips.current[Number(index)]).reset().play();
  };
  return (
    <section className="model-inspector">
      <div className="model-canvas" ref={host} aria-label="三维资源预览" />
      {!loaded && !error && <p className="panel-note">正在解析模型…</p>}
      {error && <p className="error-note">{error}</p>}
      {loaded && (
        <>
          <div className="preview-stats">
            <span>{stats.meshes} 网格</span>
            <span>{stats.bones} 骨骼</span>
            <span>{stats.triangles.toLocaleString()} 三角面</span>
            <span>{shapes.length} 形态</span>
          </div>
          <label>
            原始动画
            <select
              value={selected}
              onChange={(e) => changeClip(e.target.value)}
            >
              <option value="">默认姿态</option>
              {animations.map((name, i) => (
                <option key={i} value={i}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-choice">
            <input
              type="checkbox"
              checked={wireframe}
              onChange={(e) => {
                setWireframe(e.target.checked);
                root.current?.traverse((o) => {
                  const m = o as THREE.Mesh;
                  if (m.isMesh)
                    for (const material of Array.isArray(m.material)
                      ? m.material
                      : [m.material])
                      if ("wireframe" in material)
                        (material as THREE.MeshStandardMaterial).wireframe =
                          e.target.checked;
                });
              }}
            />
            显示网格结构
          </label>
          {boneNames.length > 0 && (
            <details>
              <summary>骨骼结构</summary>
              <pre className="management-json">
                {boneNames.map((b) => b.parent + " → " + b.name).join("\n")}
              </pre>
            </details>
          )}
          {shapes.length > 0 && (
            <details>
              <summary>表情与形态</summary>
              <div className="shape-list">
                {shapes.map((s, i) => (
                  <label key={i}>
                    {s.name}
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step=".01"
                      defaultValue="0"
                      onChange={(e) => {
                        if (s.mesh.morphTargetInfluences)
                          s.mesh.morphTargetInfluences[s.index] = Number(
                            e.target.value,
                          );
                      }}
                    />
                  </label>
                ))}
              </div>
            </details>
          )}
          <p className="panel-note">
            拖动旋转，滚轮或双指缩放。网页预览用于检查模型、骨骼和原始动画；Unity
            专用材质的最终效果以 App 为准。
          </p>
        </>
      )}
    </section>
  );
}
