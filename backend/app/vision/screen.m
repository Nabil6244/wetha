// On-device image screening with Apple's Vision framework (macOS). No network, no model download.
// Build: clang -O2 -fobjc-arc -framework Foundation -framework Vision screen.m -o screen
// Usage: screen <image> [...]  -> one JSON object per line:
//   {"path", "labels": [[label, confidence]...], "text": [[string, confidence]...], "text_regions": n}
#import <Foundation/Foundation.h>
#import <Vision/Vision.h>

static NSDictionary *screen(NSString *path) {
    NSURL *url = [NSURL fileURLWithPath:path];
    VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithURL:url options:@{}];
    VNClassifyImageRequest *classify = [[VNClassifyImageRequest alloc] init];
    VNRecognizeTextRequest *recognize = [[VNRecognizeTextRequest alloc] init];
    recognize.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
    if (@available(macOS 13.0, *)) { recognize.automaticallyDetectsLanguage = YES; }
    VNDetectTextRectanglesRequest *regions = [[VNDetectTextRectanglesRequest alloc] init];
    NSError *error = nil;
    if (![handler performRequests:@[classify, recognize, regions] error:&error]) {
        return @{@"path": path, @"error": error.localizedDescription ?: @"failed"};
    }
    NSMutableArray *labels = [NSMutableArray array];
    for (VNClassificationObservation *o in classify.results) {
        if (o.confidence > 0.05 && labels.count < 25) [labels addObject:@[o.identifier, @(o.confidence)]];
    }
    NSMutableArray *text = [NSMutableArray array];
    for (VNRecognizedTextObservation *o in recognize.results) {
        VNRecognizedText *best = [[o topCandidates:1] firstObject];
        if (best) [text addObject:@[best.string, @(best.confidence)]];
    }
    return @{@"path": path, @"labels": labels, @"text": text, @"text_regions": @(regions.results.count)};
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        for (int i = 1; i < argc; i++) {
            NSDictionary *result = screen([NSString stringWithUTF8String:argv[i]]);
            NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
            printf("%s\n", [[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] UTF8String]);
        }
    }
    return 0;
}
