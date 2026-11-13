//! Scoped GTK3 input regions for Eww 0.6; no external Rust crates.
//! Bindings use GTK/GDK's public C ABI. Applied only to our capsule classes.
use std::ffi::{c_char,c_int,c_void};
use std::{env,fs,path::PathBuf};
#[repr(C)] struct Rect { x:c_int,y:c_int,width:c_int,height:c_int }
#[repr(C)] struct List { data:*mut c_void,next:*mut List,prev:*mut List }
#[repr(C)] struct Color {r:f64,g:f64,b:f64,a:f64}
unsafe extern "C" {
    fn dlsym(handle:*mut c_void,name:*const c_char)->*mut c_void;
    fn gtk_widget_get_style_context(widget:*mut c_void)->*mut c_void;
    fn gtk_style_context_has_class(context:*mut c_void,name:*const c_char)->c_int;
    fn gtk_style_context_get_background_color(context:*mut c_void,state:c_int,color:*mut Color);
    fn gtk_widget_get_visible(widget:*mut c_void)->c_int;
    fn gtk_widget_get_child_visible(widget:*mut c_void)->c_int;
    fn gtk_widget_get_allocated_width(widget:*mut c_void)->c_int;
    fn gtk_widget_get_allocated_height(widget:*mut c_void)->c_int;
    fn gtk_widget_translate_coordinates(widget:*mut c_void,destination:*mut c_void,x:c_int,y:c_int,out_x:*mut c_int,out_y:*mut c_int)->c_int;
    fn gtk_widget_get_window(widget:*mut c_void)->*mut c_void;
    fn gtk_container_get_type()->usize;
    fn gtk_window_get_type()->usize;
    fn gtk_bin_get_child(widget:*mut c_void)->*mut c_void;
    fn gtk_widget_get_preferred_height_for_width(widget:*mut c_void,width:c_int,minimum:*mut c_int,natural:*mut c_int);
    fn gtk_window_resize(widget:*mut c_void,width:c_int,height:c_int);
    fn gtk_widget_set_size_request(widget:*mut c_void,width:c_int,height:c_int);
    fn gtk_stack_get_type()->usize;
    fn gtk_stack_get_visible_child_name(widget:*mut c_void)->*const c_char;
    fn gtk_stack_get_homogeneous(widget:*mut c_void)->c_int;
    fn g_object_get_data(object:*mut c_void,key:*const c_char)->*mut c_void;
    fn g_object_set_data(object:*mut c_void,key:*const c_char,data:*mut c_void);
    fn g_type_check_instance_is_a(instance:*mut c_void,kind:usize)->c_int;
    fn gtk_container_get_children(container:*mut c_void)->*mut List;
    fn g_list_free(list:*mut List);
    fn g_signal_connect_data(instance:*mut c_void,signal:*const c_char,callback:unsafe extern "C" fn(),data:*mut c_void,destroy:*mut c_void,flags:c_int)->u64;
    fn cairo_region_create()->*mut c_void;
    fn cairo_region_union_rectangle(region:*mut c_void,rectangle:*const Rect)->c_int;
    fn cairo_region_destroy(region:*mut c_void);
    fn gdk_window_input_shape_combine_region(window:*mut c_void,region:*mut c_void,x:c_int,y:c_int);
    fn gtk_layer_is_layer_window(window:*mut c_void)->c_int;
    fn gtk_layer_get_exclusive_zone(window:*mut c_void)->c_int;
    fn gtk_layer_set_exclusive_zone(window:*mut c_void,exclusive_zone:c_int);
}
unsafe fn class(widget:*mut c_void,name:&[u8])->bool { unsafe {gtk_style_context_has_class(gtk_widget_get_style_context(widget),name.as_ptr().cast())!=0} }
unsafe fn colors(widget:*mut c_void,values:&mut Vec<String>){unsafe {
    if gtk_widget_get_visible(widget)==0 || gtk_widget_get_child_visible(widget)==0{return;}
    if class(widget,b"island\0") || class(widget,b"pill\0") || class(widget,b"segment\0") {
        let mut c=Color{r:0.,g:0.,b:0.,a:0.};gtk_style_context_get_background_color(gtk_widget_get_style_context(widget),0,&mut c);
        values.push(format!("[{},{},{},{}]",c.r,c.g,c.b,c.a));
    }
    if g_type_check_instance_is_a(widget,gtk_container_get_type())!=0 {
        let list=gtk_container_get_children(widget);let mut item=list;
        while !item.is_null(){colors((*item).data,values);item=(*item).next;}
        g_list_free(list);
    }
}}
unsafe fn stacks(widget:*mut c_void,values:&mut Vec<String>){unsafe {
    if g_type_check_instance_is_a(widget,gtk_stack_get_type())!=0 {
        let name=gtk_stack_get_visible_child_name(widget);
        let selected=if name.is_null(){String::new()}else{std::ffi::CStr::from_ptr(name).to_string_lossy().into_owned()};
        let(mut min,mut nat)=(0,0);gtk_widget_get_preferred_height_for_width(widget,gtk_widget_get_allocated_width(widget),&mut min,&mut nat);
        values.push(format!("{{\"selected\":\"{}\",\"homogeneous\":{},\"min\":{},\"nat\":{}}}",selected,gtk_stack_get_homogeneous(widget),min,nat));
    }
    if g_type_check_instance_is_a(widget,gtk_container_get_type())!=0 {
        let list=gtk_container_get_children(widget);let mut item=list;
        while !item.is_null(){stacks((*item).data,values);item=(*item).next;}g_list_free(list);
    }
}}
unsafe fn walk(widget:*mut c_void,window:*mut c_void,rectangles:&mut Vec<(Rect,i32)>,kind:&mut &'static str,stop_at_island:bool) {
    unsafe {
        if gtk_widget_get_visible(widget)==0 || gtk_widget_get_child_visible(widget)==0 {return;}
        let island=class(widget,b"island\0");let pill=class(widget,b"pill\0") || class(widget,b"workspace\0");
        if island || pill {
            if island {*kind="island";} else if class(widget,b"clock\0") {*kind="right";}
            let(mut x,mut y)=(0,0);
            if gtk_widget_translate_coordinates(widget,window,0,0,&mut x,&mut y)!=0 {
                rectangles.push((Rect{x,y,width:gtk_widget_get_allocated_width(widget),height:gtk_widget_get_allocated_height(widget)},if island {22} else {gtk_widget_get_allocated_height(widget)/2}));
            }
            if island && stop_at_island {return;} // The whole capsule contains all of its controls.
        }
        if g_type_check_instance_is_a(widget,gtk_container_get_type())!=0 {
            let list=gtk_container_get_children(widget);let mut item=list;
            while !item.is_null() {walk((*item).data,window,rectangles,kind,stop_at_island);item=(*item).next;}
            g_list_free(list);
        }
    }
}
unsafe fn update(widget:*mut c_void) {
    unsafe {
        let native=gtk_widget_get_window(widget);if native.is_null(){return;}
        let mut rectangles=Vec::new();let mut kind="left";walk(widget,widget,&mut rectangles,&mut kind,true);
        if rectangles.is_empty(){return;} // Leave menus/tooltips and foreign windows alone.
        let mut actual_exclusive_zone=0;
        if gtk_layer_is_layer_window(widget)!=0 {
            let target=if kind=="island" {
                env::var("SELANDIA_EWW_EXCLUSIVE_ZONE").ok().and_then(|v| v.parse::<i32>().ok()).filter(|&v| v>0).unwrap_or(0)
            } else {
                -1
            };
            if gtk_layer_get_exclusive_zone(widget)!=target {
                gtk_layer_set_exclusive_zone(widget,target);
            }
            actual_exclusive_zone=gtk_layer_get_exclusive_zone(widget);
        }
        let mut preferred=0;
        if kind=="island" {
            // GTK toplevels grow for an expanded Stack but do not automatically
            // shrink again. Resize to the visible child's preferred height;
            // never reallocate widgets synchronously inside size-allocate.
            let child=gtk_bin_get_child(widget);
            if !child.is_null(){
                let(mut minimum,mut natural)=(0,0);
                let width=gtk_widget_get_allocated_width(widget);
                gtk_widget_get_preferred_height_for_width(child,width,&mut minimum,&mut natural);
                let height=natural.max(44);
                preferred=height;
                if height!=gtk_widget_get_allocated_height(widget){
                    // Follow GTK3 Layer Shell's documented forcing-size path.
                    gtk_widget_set_size_request(widget,-1,height);
                    gtk_window_resize(widget,1,1);
                }
            }
        }
        let region=cairo_region_create();
        for (rectangle,radius) in &rectangles {
            let radius=(*radius).min(rectangle.width/2).min(rectangle.height/2).max(0) as f64;
            for row in 0..rectangle.height {
                let distance=if (row as f64)<radius {radius-row as f64-0.5} else if row as f64>=rectangle.height as f64-radius {row as f64+0.5-(rectangle.height as f64-radius)} else {0.0};
                let inset=if distance>0.0 {(radius-(radius*radius-distance*distance).max(0.0).sqrt()).ceil() as i32} else {0};
                let stripe=Rect{x:rectangle.x+inset,y:rectangle.y+row,width:(rectangle.width-2*inset).max(0),height:1};
                if stripe.width>0 {cairo_region_union_rectangle(region,&stripe);}
            }
        }
        gdk_window_input_shape_combine_region(native,region,0,0);cairo_region_destroy(region);
        if let Some(root)=env::var_os("SELANDIA_EWW_GEOMETRY") {
            let root=PathBuf::from(root);let _=fs::create_dir_all(&root);
            let rects=rectangles.iter().map(|(r,_)|format!("{{\"x\":{},\"y\":{},\"width\":{},\"height\":{}}}",r.x,r.y,r.width,r.height)).collect::<Vec<_>>().join(",");
            let mut palette=Vec::new();colors(widget,&mut palette);
            let mut debug=Vec::new();let mut controls=Vec::new();
            if env::var("SELANDIA_PRIVATE_PROBE").ok().as_deref()==Some("1"){
                stacks(widget,&mut debug);let mut unused="left";walk(widget,widget,&mut controls,&mut unused,false);
            }
            let control_rects=controls.iter().map(|(r,_)|format!("{{\"x\":{},\"y\":{},\"width\":{},\"height\":{}}}",r.x,r.y,r.width,r.height)).collect::<Vec<_>>().join(",");
            let text=format!("{{\"kind\":\"{}\",\"width\":{},\"height\":{},\"preferred_height\":{},\"exclusive_zone\":{},\"capsules\":[{}],\"colors\":[{}],\"stacks\":[{}],\"controls\":[{}]}}",kind,gtk_widget_get_allocated_width(widget),gtk_widget_get_allocated_height(widget),preferred,actual_exclusive_zone,rects,palette.join(","),debug.join(","),control_rects);
            let temporary=root.join(format!("{}.partial",kind));let final_path=root.join(format!("{}.json",kind));
            if fs::write(&temporary,text).is_ok(){let _=fs::rename(temporary,final_path);}
        }
    }
}
unsafe extern "C" fn allocated(widget:*mut c_void,_allocation:*mut c_void,_data:*mut c_void){unsafe {update(widget);}}
unsafe extern "C" fn mapped(widget:*mut c_void,_event:*mut c_void,_data:*mut c_void)->c_int{unsafe {update(widget);}0}
unsafe fn attach(window:*mut c_void) {
    unsafe {
        if g_type_check_instance_is_a(window,gtk_window_get_type())==0{return;}
        let key=b"selandia-input-attached\0".as_ptr().cast();
        if g_object_get_data(window,key).is_null(){
            g_object_set_data(window,key,1usize as *mut c_void);
            g_signal_connect_data(window,b"size-allocate\0".as_ptr().cast(),std::mem::transmute(allocated as unsafe extern "C" fn(*mut c_void,*mut c_void,*mut c_void)),std::ptr::null_mut(),std::ptr::null_mut(),1);
            g_signal_connect_data(window,b"map-event\0".as_ptr().cast(),std::mem::transmute(mapped as unsafe extern "C" fn(*mut c_void,*mut c_void,*mut c_void)->c_int),std::ptr::null_mut(),std::ptr::null_mut(),1);
        }
        update(window);
    }
}
#[unsafe(no_mangle)] pub unsafe extern "C" fn gtk_widget_show_all(widget:*mut c_void){unsafe {
    let pointer=dlsym((-1isize) as *mut c_void,b"gtk_widget_show_all\0".as_ptr().cast());
    if !pointer.is_null(){let original:unsafe extern "C" fn(*mut c_void)=std::mem::transmute(pointer);original(widget);attach(widget);}
}}
#[unsafe(no_mangle)] pub unsafe extern "C" fn gtk_widget_show(widget:*mut c_void){unsafe {
    let pointer=dlsym((-1isize) as *mut c_void,b"gtk_widget_show\0".as_ptr().cast());
    if !pointer.is_null(){let original:unsafe extern "C" fn(*mut c_void)=std::mem::transmute(pointer);original(widget);attach(widget);}
}}
#[unsafe(no_mangle)] pub unsafe extern "C" fn gtk_window_new(kind:c_int)->*mut c_void {
    unsafe {
        let pointer=dlsym((-1isize) as *mut c_void,b"gtk_window_new\0".as_ptr().cast());
        if pointer.is_null(){return std::ptr::null_mut();}
        let original:unsafe extern "C" fn(c_int)->*mut c_void=std::mem::transmute(pointer);let window=original(kind);
        if !window.is_null(){attach(window);}
        window
    }
}
